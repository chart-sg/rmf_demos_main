#!/usr/bin/env python3

# Copyright 2026 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Resume an interrupted task, or reroute the robot to a new task."""

import argparse
import asyncio
import json
import sys
import uuid

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy as Durability
from rclpy.qos import QoSHistoryPolicy as History
from rclpy.qos import QoSProfile
from rclpy.qos import QoSReliabilityPolicy as Reliability

from rmf_task_msgs.msg import ApiRequest, ApiResponse

###############################################################################


class TaskRequester(Node):
    """Task requester."""

    def __init__(self, argv=sys.argv):
        """Initialize a task requester."""
        super().__init__('task_requester')
        parser = argparse.ArgumentParser()
        parser.add_argument('-id', '--for_task', required=True, type=str,
                            help='ID of the interrupted task')
        parser.add_argument('-t', '--token', required=True, type=str,
                            nargs='+',
                            help='Interruption token(s) returned by '
                                 'interrupt_robot')
        parser.add_argument('-l', '--labels', required=False, default=[],
                            type=str, nargs='+',
                            help='Labels describing this resume request')
        parser.add_argument('--new-task', required=False, default=None,
                            type=str,
                            help='Cancel the interrupted task and reroute the '
                                 'robot to an arbitrary task, given as an '
                                 'inline task_request JSON string')
        parser.add_argument('--requester', required=False,
                            default='rmf_demos_tasks', type=str,
                            help='Entity requesting the new task')

        self.args = parser.parse_args(argv[1:])
        self.response = asyncio.Future()

        # Parse the optional replacement task from the inline JSON string.
        new_task = None
        if self.args.new_task is not None:
            try:
                new_task = json.loads(self.args.new_task)
            except json.JSONDecodeError as e:
                parser.error(f'--new-task is not valid JSON: {e}')
            if not isinstance(new_task, dict):
                parser.error(
                    '--new-task must be a JSON object')
            if 'category' not in new_task or 'description' not in new_task:
                parser.error(
                    "--new-task must contain 'category' and "
                    "'description'")
            new_task['requester'] = self.args.requester

        transient_qos = QoSProfile(
            history=History.KEEP_LAST,
            depth=1,
            reliability=Reliability.RELIABLE,
            durability=Durability.TRANSIENT_LOCAL)

        self.pub = self.create_publisher(
            ApiRequest, 'task_api_requests', transient_qos
        )

        # Construct task.
        msg = ApiRequest()
        msg.request_id = 'resume_robot_' + str(uuid.uuid4())
        payload = {
            'type': 'resume_task_request',
            'for_task': self.args.for_task,
            'for_tokens': self.args.token,
        }
        if self.args.labels:
            payload['labels'] = self.args.labels
        if new_task is not None:
            # Note: unix_millis_earliest_start_time is intentionally omitted
            # so the fleet adapter deploys the replacement task immediately.
            payload['new_task'] = new_task

        msg.json_msg = json.dumps(payload)
        print(f'msg: \n{json.dumps(payload, indent=2)}')

        def receive_response(response_msg: ApiResponse):
            if response_msg.request_id == msg.request_id:
                self.response.set_result(json.loads(response_msg.json_msg))

        self.sub = self.create_subscription(
            ApiResponse, 'task_api_responses', receive_response, 10
        )

        self.pub.publish(msg)


###############################################################################


def main(argv=sys.argv):
    """Resume an interrupted task, optionally rerouting to a new task."""
    rclpy.init(args=sys.argv)
    args_without_ros = rclpy.utilities.remove_ros_args(sys.argv)

    task_requester = TaskRequester(args_without_ros)
    rclpy.spin_until_future_complete(
        task_requester, task_requester.response, timeout_sec=5.0)
    if task_requester.response.done():
        result = task_requester.response.result()
        print(f'Got response:\n{result}')
        if not result.get('success'):
            print('Request failed; the task remains interrupted.')
        elif task_requester.args.new_task is not None:
            new_task_id = result.get('state', {}) \
                .get('booking', {}).get('id')
            print(f'Task [{task_requester.args.for_task}] cancelled; '
                  f'robot rerouted to new task [{new_task_id}]')
        else:
            print(f'Task [{task_requester.args.for_task}] resumed')
    else:
        print('Did not get a response')
    rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
