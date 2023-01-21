import sys, time

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")
# currentFilePath = pathlib.Path(__file__).parent.resolve()
# sys.path.append(str(currentFilePath) + "/PythonARBIFramework")

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.agent import arbi_agent_executor
from arbi_agent.ltm.data_source import DataSource
from arbi_agent.model import generalized_list_factory
from arbi_agent.configuration import BrokerType

broker_host = "127.0.0.1"
# broker_host = "192.168.100.10"
# broker_host = "172.16.165.141"
# broker_host = "192.168.100.10"
broker_port = 61316
# broker_type = BrokerType.ACTIVE_MQ
broker_type = BrokerType.ZERO_MQ


def msg_parser(navigate_msg, c):
    return [navigate_msg.get_expression(i).as_value().string_value() for i in c]


def retrieve_all_vertex():
    with open("../MultiAgentPathFinder/map_parse/map_cloud.txt", "r") as map_info:
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
        print("on notify : " + notification)


class NavigationController(ArbiAgent):
    def __init__(self, host, port):
        super().__init__()
        arbi_agent_executor.execute(broker_host=host, broker_port=port,
                                    agent_name="agent://www.arbi.com/NavigationController",
                                    agent=self, broker_type=broker_type, daemon=False)

        self.ds = NCDataSource(self)
        self.ds.connect(broker_host, broker_port, "ds://www.arbi.com/NavigationController", broker_type)

        self.request_queue = []
        self.node_queue = retrieve_all_vertex()

        self.robot_id_list = ["AMR_LIFT1", "AMR_LIFT2", "AMR_LIFT3", "AMR_LIFT4"]
        self.multipath = {r: [] for r in self.robot_id_list}
        self.robot_state = {r: 'entered' for r in self.robot_id_list}
        self.action_id = {r: str() for r in self.robot_id_list}
        self.robot_position = {r: self.retrieve_robot_at(r) for r in self.robot_id_list}
        self.state_seq = {'moving_last_block': 'waiting_for_entering', 'pausing': 'paused',
                          'entering': 'entered', 'exiting': 'exited', 'moving': 'waiting_for_moving'}
        self.state_seq_inv = {'entered': 'exiting', 'waiting_for_entering': 'entering'}
        self.pause_switch = False
        for r in self.robot_id_list:
            self.node_queue[self.robot_position[r]] = [r]

        while len(self.request_queue) != len(self.robot_id_list):
            time.sleep(1)

        while True:
            self.update_node_queue()
            self.process_request_queue_1()
            if not self.pause_switch:
                self.process_request_queue_2()
                self.execute_multipath()
            else:
                self.process_request_queue_3()
            time.sleep(1)

    def retrieve_robot_at(self, robot_id):
        query = f'(context (robotAt \"{robot_id}\" $v1 $v2))'
        while True:
            query_result = self.ds.retrieve_fact(query)
            if query_result == "(error)":
                print("Waiting for robot Info " + str(robot_id) + "...")
                time.sleep(1)
            else:
                gl_query_result = generalized_list_factory.new_gl_from_gl_string(query_result)
                result = gl_query_result.get_expression(0).as_generalized_list()
                return str(result.get_expression(1).as_value().int_value())

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
            if self.request_queue[i].get_name() == "RequestEnterToStation":
                nav_msg = self.request_queue.pop(i)
                robot_id, end_vertex = msg_parser(nav_msg, [1, 3])
                self.send_enter_exit_msg(nav_msg)
                self.action_id[robot_id] = nav_msg.get_expression(0).as_value().string_value()
                self.node_queue[end_vertex] = [robot_id]

    def process_request_queue_2(self):
        if self.request_queue:
            nav_msg = self.request_queue[0]
            action_id, robot_id, start_vertex, end_vertex = msg_parser(nav_msg, [0, 1, 2, 3])
            if nav_msg.get_name() == "RequestExitFromStation":
                if not self.node_queue[end_vertex]:
                    self.request_queue.pop(0)
                    self.send_enter_exit_msg(nav_msg)
                    self.action_id[robot_id] = action_id
                    self.node_queue[end_vertex] = [robot_id]

            else:  # RequestNavigate
                single_path = self.request_single_path(start_vertex, end_vertex)
                single_path_flag = True  # possible to start
                for n in single_path:
                    if self.node_queue[n]:
                        single_path_flag = False
                        break

                if single_path_flag:
                    self.request_queue.pop(0)
                    self.action_id[robot_id] = action_id
                    self.send_navigate_msg(robot_id, single_path)
                    for n in single_path:
                        self.node_queue[n] = [robot_id]

                else:
                    self.pause_switch = True
                    for robot_id in self.robot_id_list:
                        if self.robot_state[robot_id] == 'moving':
                            move_msg = f'(RequestPause\"{robot_id}+Move"\""{robot_id}'
                            self.request("agent://www.arbi.com/TaskManager", move_msg)

    def process_request_queue_3(self):
        for robot_id in self.robot_id_list:
            if self.robot_state[robot_id] not in ['paused', 'entered']:
                break
        else:
            for i in range(len(self.request_queue) - 1, -1, -1):
                if self.request_queue[i].get_name() == "RequestNavigate":
                    action_id, robot_id, end_vertex = msg_parser(self.request_queue.pop(i), [0, 1, 3])
                    self.multipath[robot_id] = [end_vertex]
                    self.action_id[robot_id] = action_id

            request_msg = str()
            for r in self.robot_id_list:
                start = self.robot_position[r]
                end = self.multipath[r][-1] if self.multipath[r] else start
                request_msg += f'(RobotPath\"{r}\"{start} {end})'

            self.request_multipath(request_msg)
            self.pause_switch = False

    def execute_multipath(self):
        for robot_id in self.robot_id_list:
            if self.robot_state[robot_id] == 'waiting_for_moving':
                block_len = 1
                for idx in range(1, len(self.multipath[robot_id])):
                    if self.multipath[robot_id][idx] == self.node_queue[self.robot_position[robot_id]][0]:
                        block_len += 1
                    else:
                        break

                if block_len > 1:
                    self.send_navigate_msg(robot_id, self.multipath[robot_id][:block_len])

    def request_multipath(self, multipath_str):
        request_msg = f'(MultiRobotPath{multipath_str})'
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
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
                if self.multipath[k]:
                    self.node_queue[self.multipath[k][i]].append(k)

        remove_overlap(self.node_queue)
        remove_overlap(self.multipath)
        for r in self.robot_id_list:
            if self.multipath[r]:
                self.robot_state[r] = 'waiting_for_moving'

    def request_single_path(self, sv, ev):
        request_msg = f"(MultiRobotPath(path\"single_path_check\"{sv} {ev}))"
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        temp_gl = response_gl.get_expression(0).as_generalized_list()
        return str(temp_gl.get_expression(1))[:-1].split(' ')[1:]

    def on_data(self, sender: str, data: str):
        print(f'ON DATA\nsender : {sender}\non data : {data}\n')
        action_id = generalized_list_factory.new_gl_from_gl_string(data).get_expression(0).as_value().string_value()
        robot_id = action_id.split('+')[0]

        self.robot_state[robot_id] = self.state_seq[self.robot_state[robot_id]]
        if self.robot_state[robot_id] in ['moving_last_block', 'entering', 'exiting']:
            action_result = f'(ActionResult\"{self.action_id[robot_id]}\"(ok)\")'
            self.send("agent://www.arbi.com/TaskManager", action_result)

        print('robot state', self.robot_state)
        print('curr_position', self.robot_position)
        for k, v in self.node_queue.items():
            if v:
                print(k, v)
        for k, v in self.multipath.items():
            print(k, v)

    def on_request(self, sender: str, request: str) -> str:
        print(f'ON REQUEST\nsender : {sender}\non request : {request}\n')
        self.request_queue.append(generalized_list_factory.new_gl_from_gl_string(request))
        return '(ok)'

    def send_navigate_msg(self, robot_id, path):
        path = ' '.join(path)
        path = f'\"(Path {path}))'  # move_msg = "(RequestMove \"" + robot_id + "+Move_" + str(end_vertex[-1]) + "\"\"" + robot_id + path
        move_msg = f'(RequestMove\"LTM+{robot_id}+Move\"{robot_id} {path}'
        self.request("agent://www.arbi.com/TaskManager", move_msg)
        self.robot_state[robot_id] = 'moving'
        if len(path) == len(self.multipath[robot_id]):
            self.robot_state[robot_id] = 'moving_last_block'

    def send_enter_exit_msg(self, nav_msg):
        robot_id, move_type, vertex, direction = self.msg_parser(nav_msg, [1, 2, 3, 4])
        request_msg = f"(RequestStation{'in' or 'out'}\"{action_id}\"{robot_id}\"{move_type}\"{vertex}\"{direction}\")"
        self.request("agent://www.arbi.com/TaskManager", request_msg)
        self.robot_state[robot_id] = self.state_seq_inv[self.robot_state[robot_id]]


if __name__ == '__main__':
    nc = NavigationController(broker_host, broker_port)
    while True:
        pass
