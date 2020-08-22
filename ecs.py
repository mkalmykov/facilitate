#! /usr/bin/env python3

import subprocess
import sys
from itertools import chain

import boto3
import click
from halo import Halo
from PyInquirer import prompt


@click.group()
def ecs():
    pass


@ecs.command()
@click.option("--cluster")
@click.option("--service")
@click.option("--container")
@click.option("--user", default="ec2-user")
@click.option(
    "-i", "--identity-file", default="~/.ssh/id_rsa",
)
@click.argument("command", nargs=-1)
def exec(cluster, service, container, user, identity_file, command):
    normalized_command = " ".join(command)

    ecs_client = boto3.client("ecs")
    ec2_client = boto3.client("ec2")

    with Halo(
        text="Obtaining ARNs of running ECS tasks with EC2 launch type",
        text_color="white",
        color="green",
    ) as sp:
        list_tasks_response = ecs_client.list_tasks(
            cluster=cluster,
            serviceName=service,
            desiredStatus="RUNNING",
            launchType="EC2",
        )
        target_task_arns = list_tasks_response["taskArns"]

        sp.succeed()

    if len(target_task_arns) == 0:
        click.echo(
            click.style("\nCould not find target tasks. Exiting!", fg="red", bold=True)
        )
        sys.exit(1)

    for task_arn in target_task_arns:
        click.echo(click.style(f"  - {task_arn}", fg="green"))

    with Halo(
        text="Obtaining container instance ARNs", text_color="white", color="green"
    ) as sp:
        describe_tasks_response = ecs_client.describe_tasks(
            cluster=cluster, tasks=target_task_arns,
        )
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

    with Halo(
        text="Obtaining container instance IDs", text_color="white", color="green"
    ) as sp:
        describe_container_instances_response = ecs_client.describe_container_instances(
            cluster=cluster, containerInstances=container_instance_arns,
        )
        container_instance_ids = [
            container_instance["ec2InstanceId"]
            for container_instance in describe_container_instances_response[
                "containerInstances"
            ]
        ]

        sp.succeed()

    for instance_id in container_instance_ids:
        click.echo(click.style(f"  - {instance_id}", fg="green"))

    with Halo(
        text="Obtaining container instance IP addresses",
        text_color="white",
        color="green",
    ) as sp:
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
    target_instance_ip = target_instance_ip_answer["target_instance_ip"]

    should_exec_answer = prompt(
        [
            {
                "type": "confirm",
                "message": f'You are about to execute "{normalized_command}" in the container "{container}" running on the instance "{target_instance_ip}". Do you want to continue?',
                "name": "should_exec",
                "default": True,
            }
        ]
    )
    should_exec = should_exec_answer["should_exec"]

    if not should_exec:
        click.echo(click.style("\nOperation aborted. Exiting!", fg="red", bold=True))
        return

    click.echo()

    return subprocess.call(
        f"ssh -i {identity_file} {user}@{target_instance_ip} -t 'bash -c \"docker exec -it $(docker ps -q -f name='-{container}-' | head -n 1) {normalized_command}\"'",
        shell=True,
    )


if __name__ == "__main__":
    ecs()
