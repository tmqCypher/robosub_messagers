import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import Executor, MultiThreadedExecutor
from rclpy.node import Node

from robosub_interfaces.msg import RFM9xPayload, ID
from robosub_messagers.robosub_pb2 import ControllerMessage


class CommandParser(Node):
    '''Reads a controller message and follows its commands'''

    def __init__(self, executor: Executor):
        super().__init__(node_name='command_parser', parameter_overrides=[])

        self.log = self.get_logger()
        self.executor: Executor = executor
        self._command_client_group = ReentrantCallbackGroup()
        self._timer_group = MutuallyExclusiveCallbackGroup()

        self._timer = self.create_timer(0.5, self._timer_callback, self._timer_group)

        # Track messages that were dropped/sent out of order
        self._commands: dict[int, ControllerMessage] = {}
        self._latest_received = -1
        self._latest_handled = -1

        self._cmd_sub = self.create_subscription(RFM9xPayload, 'cmd_data',
                self._cmd_sub_callback, 10)
        self._resend_pub = self.create_publisher(ID, 'resend_request', 1)

    def _timer_callback(self):
        '''Handle queued commands'''
        # If the next message exists, handle it
        if ((self._latest_handled + 1) in self._commands
             and self._commands[self._latest_handled + 1] is not None):
            # Update latest handled, update commands queue
            self._latest_handled += 1
            msg = self._commands[self._latest_handled]
            del(self._commands[self._latest_handled])
            
            # TODO: Placeholder until we get coordinated with engineers
            self.log.info(f'Handling controller message:\n{msg}')

    def _cmd_sub_callback(self, msg):
        '''Parse and queue the commands in the message'''
        ctrl_msg = ControllerMessage()
        ctrl_msg.ParseFromString(bytes(msg.payload))
        self.log.info(f'Received {ctrl_msg.id} (expecting {self._latest_received + 1})')

        # Check that this is the next expected message
        expected = self._latest_received + 1

        # There are messages missing, add them to our commands
        if (ctrl_msg.id > expected):
            for id in range(expected, ctrl_msg.id):
                self._commands[id] = None
            self._commands[ctrl_msg.id] = ctrl_msg
            self._latest_received = ctrl_msg.id
            self.log.warning(f'Received {ctrl_msg.id} when expecting {expected}')

        # This is a resend.
        elif (ctrl_msg.id < expected):
            if (ctrl_msg.id not in self._commands
                or self._commands[ctrl_msg.id] is None):
                # Add the missing message
                self._commands[ctrl_msg.id] = ctrl_msg
                self.log.info(f'Received missing message {ctrl_msg.id}')
                self._commands[ctrl_msg.id] = ctrl_msg
            else:
                self.log.info(f'Received repeat message {ctrl_msg.id}, ignoring')

        # This was the expecetd message. *Phew*
        else:
            self._commands[ctrl_msg.id] = ctrl_msg
            self._latest_received = ctrl_msg.id
            self.log.info(f'Received message {ctrl_msg.id}')

        # Tell the telemetry composer about the first
        # missing message, if any
        for id in self._commands:
            if self._commands[id] is None:
                self._resend_pub.publish(ID(id=id))
                break


def main(args=None):
    rclpy.init(args=args)

    executor = MultiThreadedExecutor()
    node = CommandParser(executor)

    node.get_logger().info('Running')
    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
