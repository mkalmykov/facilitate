#! /usr/bin/env python3

import subprocess
import sys
from itertools import chain

import boto3
import click
from halo import Halo
from PyInquirer import prompt

ecs_client = boto3.client("ecs")
ec2_client = boto3.client("ec2")

DEFAULT_PRELOADER_STYLES = {
    "text_color": "white",
    "color": "green",
}


@click.group()
def ecs():
    pass


@ecs.command()
@click.option("--cluster")
@click.option("--service")
@click.option("--user", default="ec2-user")
@click.option(
    "-i", "--identity-file", default="~/.ssh/id_rsa",
)
@click.argument("container", nargs=1)
@click.argument("command", nargs=-1)
def exec(cluster, service, user, identity_file, container, command):
    normalized_command = " ".join(command)

    container_task_arns = _get_container_task_arns(cluster, service)
    container_instance_arns = _get_container_instance_arns(cluster, container_task_arns, container)
    container_instance_ids = _get_container_instance_ids(cluster, container_instance_arns)
    container_instance_ips = _get_container_instance_ips(container_instance_ids)
    target_instance_ip = _ask_target_instance_ip(container_instance_ips)

    _ask_should_exec(normalized_command, container, target_instance_ip)

    return _exec(identity_file, user, target_instance_ip, container, normalized_command)


def _get_container_task_arns(cluster, service):
    with Halo(
        text="Obtaining ARNs of running ECS tasks with EC2 launch type", **DEFAULT_PRELOADER_STYLES,
    ) as sp:
        list_tasks_response = ecs_client.list_tasks(
            cluster=cluster, serviceName=service, desiredStatus="RUNNING", launchType="EC2",
        )
        container_task_arns = list_tasks_response["taskArns"]

        sp.succeed()

    if len(container_task_arns) == 0:
        click.echo(click.style("\nCould not find target tasks. Exiting!", fg="red", bold=True))
        sys.exit(1)

    for task_arn in container_task_arns:
        click.echo(click.style(f"  - {task_arn}", fg="green"))

    return container_task_arns


def _get_container_instance_arns(cluster, task_arns, container):
    with Halo(text="Obtaining container instance ARNs", **DEFAULT_PRELOADER_STYLES) as sp:
        describe_tasks_response = ecs_client.describe_tasks(cluster=cluster, tasks=task_arns,)
        tasks_with_target_container = [
            t
            for t in describe_tasks_response["tasks"]
            if any(c for c in t["containers"] if c["name"] == container)
        ]
        container_instance_arns = [
            task["containerInstanceArn"] for task in tasks_with_target_container
        ]

        sp.succeed()

    for instance_arn in container_instance_arns:
        click.echo(click.style(f"  - {instance_arn}", fg="green"))

    return container_instance_arns


def _get_container_instance_ids(cluster, container_instance_arns):
    with Halo(text="Obtaining container instance IDs", **DEFAULT_PRELOADER_STYLES) as sp:
        describe_container_instances_response = ecs_client.describe_container_instances(
            cluster=cluster, containerInstances=container_instance_arns,
        )
        container_instance_ids = [
            container_instance["ec2InstanceId"]
            for container_instance in describe_container_instances_response["containerInstances"]
        ]

        sp.succeed()

    for instance_id in container_instance_ids:
        click.echo(click.style(f"  - {instance_id}", fg="green"))

    return container_instance_ids


def _get_container_instance_ips(container_instance_ids):
    with Halo(text="Obtaining container instance IP addresses", **DEFAULT_PRELOADER_STYLES,) as sp:
        describe_instances_response = ec2_client.describe_instances(
            InstanceIds=container_instance_ids,
        )

        instances = list(
            chain(
                *[
                    reservation["Instances"]
                    for reservation in describe_instances_response["Reservations"]
                ]
            )
        )
        container_instance_ips = [instance["PublicIpAddress"] for instance in instances]
        sp.succeed()

    for instance_ip in container_instance_ips:
        click.echo(click.style(f"  - {instance_ip}", fg="green"))

    return container_instance_ips


def _ask_target_instance_ip(container_instance_ips):
    target_instance_ip_answer = prompt(
        [
            {
                "type": "list",
                "name": "target_instance_ip",
                "message": "Choose EC2 instance to connect to",
                "choices": container_instance_ips,
            }
        ]
    )

    return target_instance_ip_answer["target_instance_ip"]


def _ask_should_exec(command, container, instance_ip):
    should_exec_answer = prompt(
        [
            {
                "type": "confirm",
                "message": f'You are about to execute "{command}" in the container "{container}" running on the instance "{instance_ip}". Do you want to continue?',
                "name": "should_exec",
                "default": True,
            }
        ]
    )
    should_exec = should_exec_answer["should_exec"]

    if not should_exec:
        click.echo(click.style("\nOperation aborted. Exiting!", fg="red", bold=True))
        sys.exit(0)


def _exec(identity_file, user, instance_ip, container, command):
    return subprocess.call(
        f"ssh -i {identity_file} {user}@{instance_ip} -t 'bash -c \"docker exec -it $(docker ps -q -f name='-{container}-' | head -n 1) {command}\"'",
        shell=True,
    )


if __name__ == "__main__":
    ecs()
