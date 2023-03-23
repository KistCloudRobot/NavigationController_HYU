import sys
import time
from nc_utils import msg_parser, remove_overlap, NCBase

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")

from arbi_agent.model import generalized_list_factory
from arbi_agent.configuration import BrokerType

# broker_host = "127.0.0.1"
# broker_host = "192.168.100.10"
broker_host = "172.16.165.158"
broker_port = 61316
broker_type = BrokerType.ACTIVE_MQ


class NavigationController(NCBase):
    def __init__(self):
        super().__init__(broker_host, broker_port, broker_type)
        self.request_queue = []
        self.robot_id_list = ['AMR_LIFT1', 'AMR_LIFT2', 'AMR_LIFT3', 'AMR_LIFT4']
        self.multipath = {r: [] for r in self.robot_id_list}
        self.robot_state = {r: 'returned' for r in self.robot_id_list}
        self.robot_nr_type = {r: None for r in self.robot_id_list}
        self.robot_canceled = {r: False for r in self.robot_id_list}
        self.action_id = {r: str() for r in self.robot_id_list}
        self.robot_position = {r: self.retrieve_robot_at(r) for r in self.robot_id_list}
        self.state_seq = {'moving_for_entering': 'waiting_for_entering',
                          'moving_for_return': 'returned', 'moving': 'waiting_for_moving',
                          'canceling': 'canceled', 'entering': 'entered', 'exiting': 'exited'}
        self.state_seq_inv = {'entered': 'exiting', 'waiting_for_entering': 'entering'}
        self.thr_last_block = 5
        self.cancel_switch = False
        for r in self.robot_id_list:
            self.node_queue[self.robot_position[r]] = [r]

        while len(self.request_queue) != len(self.robot_id_list):
            time.sleep(1)

        while True:
            self.update_node_queue_multipath()
            self.process_request_queue_1()
            if not self.cancel_switch:
                self.process_request_queue_2()
                self.execute_multipath()
                self.print_fn(2)
            else:
                self.process_request_queue_3()
                self.print_fn(3)
            time.sleep(1)

    def update_node_queue_multipath(self):
        for idx, r in enumerate(self.robot_id_list):
            prev_pos = self.robot_position[r]
            self.robot_position[r] = self.retrieve_robot_at(r)
            if prev_pos != self.robot_position[r]:
                self.node_queue[prev_pos].pop(0)
                if self.multipath[r]:
                    self.multipath[r].pop(0)
                    if len(self.multipath[r]) == 1:
                        self.multipath[r] = []

    def process_request_queue_1(self):
        for i in range(len(self.request_queue) - 1, -1, -1):
            if self.request_queue[i].get_name() == 'RequestEnterToStation':
                nav_msg = self.request_queue.pop(i)
                action_id, robot_id, end_vertex = msg_parser(nav_msg, [0, 1, 3])
                self.send_enter_exit_msg(nav_msg)
                self.action_id[robot_id] = action_id
                self.node_queue[end_vertex] = [robot_id]

    def process_request_queue_2(self):
        if self.request_queue:
            nav_msg = self.request_queue[0]
            action_id, robot_id, start_vertex, end_vertex = msg_parser(nav_msg, [0, 1, 2, 3])
            if nav_msg.get_name() == 'RequestExitFromStation':
                if not self.node_queue[end_vertex]:
                    self.request_queue.pop(0)
                    self.send_enter_exit_msg(nav_msg)
                    self.action_id[robot_id] = action_id
                    self.node_queue[end_vertex] = [robot_id]

            else:
                single_path = self.request_single_path(start_vertex, end_vertex)
                single_path_flag = True
                for n in single_path:
                    if self.node_queue[n]:
                        single_path_flag = False
                        break

                if single_path_flag:
                    self.request_queue.pop(0)
                    self.action_id[robot_id] = action_id
                    self.send_navigate_msg(robot_id, single_path)
                    self.robot_nr_type[robot_id] = nav_msg.get_name()
                    for n in single_path:
                        self.node_queue[n] = [robot_id]
                else:
                    self.cancel_switch = True
                    for robot_id in self.robot_id_list:
                        cancel_msg = f'(RequestCancelMove"{robot_id}+Cancel""{robot_id}")'
                        if self.robot_state[robot_id] == 'moving' or (
                                self.robot_state[robot_id] in ['moving_for_entering', 'moving_for_return'] and
                                len(self.multipath[robot_id]) > self.thr_last_block):
                            self.request("agent://www.arbi.com/TaskManager", cancel_msg)
                            self.robot_state[robot_id] = 'canceling'
                            self.robot_canceled[robot_id] = True

    def process_request_queue_3(self):
        for robot_id in self.robot_id_list:
            if self.robot_state[robot_id] not in ['returned', 'canceled', 'entered', 'exited', 'waiting_for_moving']:
                break
        else:
            for i in range(len(self.request_queue) - 1, -1, -1):
                temp_name = self.request_queue[i].get_name()
                if temp_name in ['RequestNavigate', 'RequestReturn']:
                    action_id, robot_id, end_vertex = msg_parser(self.request_queue.pop(i), [0, 1, 3])
                    self.robot_nr_type[robot_id] = temp_name
                    self.multipath[robot_id] = [end_vertex]
                    self.action_id[robot_id] = action_id

            request_msg = str()
            for r in self.robot_id_list:
                start = self.robot_position[r]
                end = self.multipath[r][-1] if self.multipath[r] else start
                request_msg += f'(RobotPath"{r}"{start} {end})'

            self.request_multipath(request_msg)
            self.cancel_switch = False

    def execute_multipath(self):
        for robot_id in self.robot_id_list:
            if self.robot_state[robot_id] == 'waiting_for_moving':
                block_len = 1
                temp_set = [self.multipath[robot_id][0]]
                for idx in range(1, len(self.multipath[robot_id])):
                    if robot_id == self.node_queue[self.multipath[robot_id][idx]][0] \
                            and self.multipath[robot_id][idx] not in temp_set:
                        block_len += 1
                        temp_set.append(self.multipath[robot_id][idx])
                    else:
                        break
                if block_len > 1:
                    self.send_navigate_msg(robot_id, self.multipath[robot_id][:block_len])

    def request_multipath(self, multipath_str):
        request_msg = f'(MultiRobotPath{multipath_str})'
        response = self.request('agent://www.arbi.com/MultiAgentPathFinder', request_msg)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        for idx, r in enumerate(self.robot_id_list):
            temp_gl = response_gl.get_expression(idx).as_generalized_list()
            path = str(temp_gl.get_expression(1))[:-1].split(' ')[1:]
            self.multipath[r] = path if len(path) > 1 else []

        for k in self.node_queue.keys():
            self.node_queue[k] = []
        for r in self.robot_id_list:
            self.node_queue[self.robot_position[r]] = [r]

        for i in range(max([len(v) for v in self.multipath.values()])):
            for k in self.multipath.keys():
                if len(self.multipath[k]) > i:
                    self.node_queue[self.multipath[k][i]].append(k)

        remove_overlap(self.node_queue)
        remove_overlap(self.multipath)
        for r in self.robot_id_list:
            if self.multipath[r]:
                self.robot_state[r] = 'waiting_for_moving'

    def request_single_path(self, sv, ev):
        request_msg = f'(MultiRobotPath(path"single_path_check"{sv} {ev}))'
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        temp_gl = response_gl.get_expression(0).as_generalized_list()
        return str(temp_gl.get_expression(1))[:-1].split(' ')[1:]

    def on_data(self, sender: str, data: str):
        print(f'ON DATA\nsender : {sender}\non data : {data}\n')
        action_id = generalized_list_factory.new_gl_from_gl_string(data).get_expression(0).as_value().string_value()
        robot_id = action_id.split('+')[0]
        if self.robot_state[robot_id] in ['moving_for_entering', 'moving_for_return', 'entering', 'exiting']:
            goal_result = f'(GoalResult"{self.action_id[robot_id]}""success")'
            print('goal_result', goal_result)
            self.robot_nr_type[robot_id] = None
            self.send("agent://www.arbi.com/TaskManager", goal_result)

        self.robot_state[robot_id] = self.state_seq[self.robot_state[robot_id]]
        for k, v in self.node_queue.items():
            if v:
                print(k, v)

    def on_request(self, sender: str, request: str) -> str:
        print(f'ON REQUEST\nsender : {sender}\non request : {request}\n')
        self.request_queue.append(generalized_list_factory.new_gl_from_gl_string(request))
        return '(ok)'

    def send_navigate_msg(self, robot_id, path):
        if self.robot_canceled[robot_id]:
            self.robot_canceled[robot_id] = False
            path = path[1:]
        path_temp = ' '.join(path)
        move_msg = f'(RequestMove"{robot_id}+Move""{robot_id}"(Path {path_temp}))'
        self.request("agent://www.arbi.com/TaskManager", move_msg)
        self.robot_state[robot_id] = 'moving'
        if path[-1] == self.multipath[robot_id][-1]:
            if self.robot_nr_type[robot_id] == 'RequestNavigate':
                self.robot_state[robot_id] = 'moving_for_entering'
            else:
                self.robot_state[robot_id] = 'moving_for_return'

    def send_enter_exit_msg(self, nav_msg):
        robot_id, move_type, vertex, direction = msg_parser(nav_msg, [1, 2, 3, 4])
        request_msg = f'(Request{move_type}"{robot_id}+EXIT_ENTER""{robot_id}"{vertex}"{direction}")'
        self.request("agent://www.arbi.com/TaskManager", request_msg)
        self.robot_state[robot_id] = self.state_seq_inv[self.robot_state[robot_id]]


if __name__ == '__main__':
    nc = NavigationController()
    while True:
        pass
