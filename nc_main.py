import sys
import time
import os
import pathlib

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")
sys.path.append("/home/uosai/pythonProject/Python-mcArbiFramework")

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.agent import arbi_agent_executor
from arbi_agent.ltm.data_source import DataSource
from arbi_agent.model import generalized_list_factory
from arbi_agent.configuration import BrokerType

broker_host = os.getenv("BROKER_ADDRESS")
if broker_host is None:
    # broker_host = "127.0.0.1"
    # broker_host = "192.168.100.10"
    broker_host = "172.16.165.185"

broker_port = os.getenv("BROKER_PORT")
if broker_port is None:
    broker_port = 61316

broker_type = BrokerType.ACTIVE_MQ

def msg_parser(msg, c):
    return [msg.get_expression(i).as_value().string_value() for i in c]


def ds_msg_parser(msg, c):
    msg = generalized_list_factory.new_gl_from_gl_string(msg)
    return [msg.get_expression(i).as_value().string_value() for i in c]


def retrieve_all_vertex():
    with open(pathlib.Path(__file__).parent.resolve() / "map_cloud.txt", "r") as map_info:
        result = {}
        info_str = map_info.read()
        for line in info_str.split('\n'):
            target = line.split(' ')
            if target[0] == '\tname':
                result[target[1]] = []

    return result


def remove_overlap(d):
    for k, v in d.items():
        if v:
            for i in range(len(v) - 1, 0, -1):
                if v[i] == v[i - 1]:
                    v.pop(i)




class NCDataSource(DataSource):
    def __init__(self, nc):
        self.nc = nc
        super().__init__()

    def on_notify(self, notification):
        print("[ON NOTIFY] : " + str(notification))
        robot_id, v1, v2 = ds_msg_parser(notification, [0, 1, 2])
        if self.nc.robot_position[robot_id]:
            if (v1, v2) != self.nc.robot_position[robot_id]:
                prev_v12 = self.nc.robot_position[robot_id]
                if v1 != self.nc.robot_position[robot_id][0]:
                    if self.nc.robot_state[robot_id] in ['entering', 'exiting']:
                        if self.nc.node_queue[prev_v12[0]] and self.nc.node_queue[prev_v12[0]][0] == robot_id:
                            self.nc.node_queue[prev_v12[0]].pop(0)
                            self.nc.robot_position[robot_id] = (v1, v2)
                    else:
                        if self.nc.node_queue[prev_v12[0]] and self.nc.node_queue[prev_v12[0]][0] == robot_id:
                            if self.nc.multipath[robot_id] and self.nc.multipath[robot_id][0] == prev_v12[0]:
                                if self.nc.multipath[robot_id][1] == v1:
                                    self.nc.node_queue[prev_v12[0]].pop(0)
                                    self.nc.multipath[robot_id].pop(0)
                                    self.nc.robot_position[robot_id] = (v1, v2)
                                    if len(self.nc.multipath[robot_id]) == 1:
                                        self.nc.multipath[robot_id] = []
                                    if self.nc.path_block_cnt[robot_id]:
                                        self.nc.path_block_cnt[robot_id][0] += 1
                else:
                    self.nc.robot_position[robot_id] = (v1, v2)
                print(f'{robot_id} position has been changed : {prev_v12} -> {(v1, v2)}')
        else:
            self.nc.robot_position[robot_id] = (v1, v2)


class NavigationController(ArbiAgent):
    def __init__(self, host, port):
        super().__init__()
        arbi_agent_executor.execute(broker_host=host, broker_port=port,
                                    agent_name="agent://www.arbi.com/NavigationController",
                                    agent=self, broker_type=broker_type, daemon=False)

        self.request_queue = []
        self.node_queue = retrieve_all_vertex()
        self.robot_id_list = ['AMR_LIFT1', 'AMR_LIFT2', 'AMR_LIFT3', 'AMR_LIFT4']
        self.multipath = {r: [] for r in self.robot_id_list}
        self.robot_state = {r: 'returned' for r in self.robot_id_list}
        self.robot_nr_type = {r: None for r in self.robot_id_list}
        self.robot_canceled = {r: False for r in self.robot_id_list}
        self.action_id = {r: str() for r in self.robot_id_list}
        self.robot_position = {r: tuple() for r in self.robot_id_list}
        self.path_block_cnt = {r: None for r in self.robot_id_list}
        self.state_seq = {'moving_for_entering': 'waiting_for_entering',
                          'moving_for_return': 'returned', 'moving': 'waiting_for_moving',
                          'canceling': 'canceled', 'entering': 'entered', 'exiting': 'exited'}
        self.state_seq_inv = {'entered': 'exiting', 'waiting_for_entering': 'entering', 'returned': 'moving'}
        self.previous_print = ''
        self.thr_last_block = 3
        self.cancel_switch = False

        self.ds = NCDataSource(self)
        self.ds.connect(broker_host, broker_port, "ds://www.arbi.com/NavigationController", broker_type)
        robot_at_subscribe = '(rule (fact (context (robotAt $robot_id $v1 $v2))) --> (notify (robotAt $robot_id $v1 $v2)))'
        subscribe_id = self.ds.subscribe(robot_at_subscribe)
        print(subscribe_id)
        time.sleep(5)
        while True:
            self.process_request_queue_1()
            if not self.cancel_switch:
                self.process_request_queue_2()
                self.execute_multipath()
                self.custom_print('fn_2')
            else:
                self.process_request_queue_3()
                self.custom_print('fn_3')
            time.sleep(0.1)

    def custom_print(self, fn_n):
        str_info = f'{fn_n}, id, state, position, nr_type, multipath\n'
        for r in self.robot_id_list:
            str_info += f'{r}, {self.robot_state[r]}, {self.robot_position[r]}'
            str_info += f', {self.robot_nr_type[r]}, {self.multipath[r]}\n'
        if str_info != self.previous_print:
            print(str_info)
            self.previous_print = str_info

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
                for n in single_path[1:]:
                    if self.node_queue[n]:
                        single_path_flag = False
                        break
                if single_path_flag:
                    self.request_queue.pop(0)
                    self.action_id[robot_id] = action_id
                    self.multipath[robot_id] = single_path
                    self.robot_nr_type[robot_id] = nav_msg.get_name()
                    for n in single_path[1:]:
                        self.node_queue[n] = [robot_id]
                    self.send_navigate_msg(robot_id, single_path)
                else:
                    self.cancel_switch = True
                    for robot_id in self.robot_id_list:
                        cancel_msg = f'(RequestCancelMove"{robot_id}+Cancel""{robot_id}")'
                        print(cancel_msg)
                        if self.robot_state[robot_id] == 'moving':
                            temp = self.path_block_cnt[robot_id]
                            if temp[1] - temp[0] > self.thr_last_block:
                                self.request("agent://www.arbi.com/TaskManager", cancel_msg)
                                self.robot_state[robot_id] = 'canceling'
                                self.robot_canceled[robot_id] = True
                                self.path_block_cnt[robot_id] = None
                        elif self.robot_state[robot_id] in ['moving_for_entering', 'moving_for_return']:
                            if len(self.multipath[robot_id]) > self.thr_last_block:
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
                start = self.robot_position[r][0]
                end = self.multipath[r][-1] if self.multipath[r] else start
                request_msg += f'(RobotPath"{r}"{start} {end})'

            self.request_multipath(request_msg)
            time.sleep(1)
            self.cancel_switch = False


    def execute_multipath(self):
        for robot_id in self.robot_id_list:
            if self.robot_state[robot_id] == 'waiting_for_moving':
                block_len = 1
                temp_set = [self.multipath[robot_id][0]]
                for idx in range(1, len(self.multipath[robot_id])):
                    if robot_id == self.node_queue[self.multipath[robot_id][idx]][0]:
                        if self.multipath[robot_id][idx] not in temp_set:
                            block_len += 1
                            temp_set.append(self.multipath[robot_id][idx])
                    else:
                        break
                if block_len > 1:
                    self.path_block_cnt[robot_id] = [0, block_len]
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
            self.node_queue[self.robot_position[r][0]] = [r]

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
            self.send("agent://www.arbi.com/TaskManager", goal_result)
            self.robot_nr_type[robot_id] = None

        self.robot_state[robot_id] = self.state_seq[self.robot_state[robot_id]]
        print(f'robot id : {robot_id}\nstate, position, path')
        for rr in self.robot_id_list:
            print(f'{rr} info : {self.robot_state[rr]}, {self.robot_position[rr]}, {self.multipath[rr]}')
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
            ver_2 = self.robot_position[robot_id][1]
            if path[1] == ver_2:
                path = path[1:]
        path_temp = ' '.join(path)
        move_msg = f'(RequestMove"{robot_id}+Move""{robot_id}"(Path {path_temp}))'
        print(f'EXIT-ENTER robot_id : {robot_id}, state : {self.robot_state[robot_id]}, block_path : {path_temp}')
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
        print(f'EXIT-ENTER robot_id : {robot_id}, move_type : {move_type}, state : {self.robot_state[robot_id]}')
        self.request("agent://www.arbi.com/TaskManager", request_msg)
        self.robot_state[robot_id] = self.state_seq_inv[self.robot_state[robot_id]]


if __name__ == '__main__':
    nc = NavigationController(broker_host, broker_port)
    while True:
        pass
