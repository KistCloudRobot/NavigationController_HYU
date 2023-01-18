import sys, time
from copy import deepcopy as dc

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")
# currentFilePath = pathlib.Path(__file__).parent.resolve()
# sys.path.append(str(currentFilePath) + "/PythonARBIFramework")

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.agent import arbi_agent_executor
from arbi_agent.ltm.data_source import DataSource
from arbi_agent.model import generalized_list_factory
from arbi_agent.configuration import BrokerType


class NCDataSource(DataSource):
    def __init__(self, nc):
        self.nc = nc

    def on_notify(self, notification):
        print("on notify : " + notification)


class NavigationController(ArbiAgent):
    def __init__(self, brokerURL):
        super().__init__()
        self.ds = NCDataSource(self)
        arbi_agent_executor.execute(broker_url=brokerURL, agent_name="agent://www.arbi.com/NavigationController",
                                    agent=self, broker_type=BrokerType.ZERO_MQ, daemon=False)
        self.request_queue = []
        self.actionID = {}
        self.subActionID = {}
        self.robot_state = {}
        self.multipath = {}
        self.robot_index = {}
        self.robot_position = {}

        self.t_node = {}
        self.robot_list = ["AMR_LIFT1", "AMR_LIFT2", "AMR_LIFT3", "AMR_LIFT4"]
        self.global_waiting = False
        self.col_flag = False
        for idx, r in enumerate(self.robot_list):
            self.actionID[r] = str()
            self.subActionID[r] = str()
            self.robot_state[r] = 'done'
            self.multipath[r] = list()
            self.robot_index[r] = idx
            self.robot_position[r] = self.retrieve_robot_at(r)
            self.t_node[self.robot_position[r]] = [r]

        while True:
            time.sleep(0.1)
            self.run()

    @staticmethod
    def msg_parser(navigate_msg, c):
        return [str(navigate_msg.get_expression(i).as_value().string_value()) for i in c]

    @staticmethod
    def action_parser(action_id):
        robot_name, move_type = action_id.split('+')
        if move_type[:4] == 'Move':
            return robot_name, 'Move', move_type.split('_')[1]
        elif move_type[:4] == 'Exit':
            return robot_name, 'Exit', None
        else:
            return robot_name, 'Enter', None

    @staticmethod
    def remove_overlap(d):
        for k, v in d.items():
            if len(v) > 1:
                for i in range(len(v) - 1, 0, -1):
                    if v[i] == v[i - 1]:
                        v.pop(i)
        return d

    def retrieve_robot_at(self, robot_id):  # input : robotID ex) AMR_LIFT1,  result : vertex ex) 1
        query = "(context(robotAt\"" + robot_id + "\"$v1 $v2))"
        while True:
            query_result = self.ds.retrieve_fact(query)
            if query_result == "(error)":
                print("Waiting for robot Info " + str(robot_id) + "...")
                time.sleep(0.1)
            else:
                gl_query_result = generalized_list_factory.new_gl_from_gl_string(query_result)
                result = gl_query_result.get_expression(0).as_generalized_list()
                return str(result.get_expression(1).as_value().int_value())

    def request_single_path(self, sv, ev):
        request_msg = "(MultiRobotPath(path\"single_path_check\"" + sv + " " + ev + "))"
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        temp_gl = response_gl.get_expression(0).as_generalized_list()
        path = str(temp_gl.get_expression(1))[:-1]
        return path.split(' ')[1:]

    def request_to_mapf(self, paths):
        request_msg = str()
        for idx, r in enumerate(self.robot_list):
            request_msg += "(RobotPath\"" + r + "\"" + paths[idx] + ")"

        request_msg = "(MultiRobotPath" + request_msg + ")"
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        multipath = {}
        for idx, r in enumerate(self.robot_list):
            temp_gl = response_gl.get_expression(idx).as_generalized_list()
            path = str(temp_gl.get_expression(1))[:-1]
            temp_split = path.split(' ')
            # print('&&&&&&&&&&&&&&&&&&&&&&&7')
            # print(temp_split)
            multipath[r] = temp_split[2:]

        self.reduce_t_node(multipath)

    def reduce_t_node(self, multipath):
        print('multipath input')
        for k ,v in multipath.items():
            print(k, v)
        t_node = {}
        for r in self.robot_list:
            t_node[self.robot_position[r]] = [r]

        temp_len = [len(v) for v in multipath.values()]
        max_len = max(temp_len)
        for i in range(max_len):
            for k in multipath.keys():
                if len(multipath[k]) > i:
                    if multipath[k][i] in t_node.keys():
                        t_node[multipath[k][i]].append(k)
                    else:
                        t_node[multipath[k][i]] = [k]
        self.t_node = self.remove_overlap(t_node)
        self.multipath = self.remove_overlap(multipath)
        for r in self.robot_list:
            if r not in self.multipath.keys():
                self.multipath[r] = []

    def run(self):
        if self.request_queue:
            navigateMsg = dc(self.request_queue[0])
            glName = navigateMsg.get_name()
            actionID, robotID, start_vertex, end_vertex = self.msg_parser(navigateMsg, [0, 1, 2, 3])
            if glName == "RequestEnterToStation":
                self.request_queue.pop(0)
                self.robot_state[robotID] = 'done'
                self.send_enter_exit_msg(navigateMsg, "+Enter")

            elif glName == "RequestExitFromStation":
                if end_vertex not in self.t_node.keys():
                    self.request_queue.pop(0)
                    self.robot_state[robotID] = 'moving'
                    self.send_enter_exit_msg(navigateMsg, "+Exit")
                    self.t_node[end_vertex] = [robotID]

            else:
                self.global_waiting = True
                pop_flag = True
                for s in self.robot_state.values():
                    if s == 'moving':
                        pop_flag = False
                        break
                if pop_flag:
                    print('pop occurs')
                    print(actionID, robotID, start_vertex, end_vertex)
                    self.request_queue.pop(0)
                    self.actionID[robotID] = actionID
                    multipath_input = []
                    self.multipath[robotID] = [end_vertex]
                    for r in self.robot_list:
                        start = self.retrieve_robot_at(r)
                        if self.multipath[r]:
                            end = self.multipath[r][-1]
                        else:
                            end = start
                        multipath_input.append(start + ' ' + end)

                    self.request_to_mapf(multipath_input)
                    self.global_waiting = False

        if not self.global_waiting:
            for robot_name in self.robot_list:
                if self.multipath[robot_name] and self.robot_state[robot_name] == 'done':
                    if self.t_node[self.multipath[robot_name][0]][0] == robot_name:
                        self.navigate_single_step(robot_name, self.multipath[robot_name][0])
                        self.robot_state[robot_name] = 'moving'
                        self.multipath[robot_name].pop(0)
    def on_start(self):
        self.ds.connect(self.broker_url, "ds://www.arbi.com/NavigationController", BrokerType.ZERO_MQ)

    def on_data(self, sender: str, data: str):
        print("\nON DATA")
        print("sender : " + sender)
        print("on data : " + data)
        gl_msg = generalized_list_factory.new_gl_from_gl_string(data)
        action_id, result = self.msg_parser(gl_msg, [0, 1])
        robot_id, move_type, vertex = self.action_parser(action_id)
        pre_position = self.robot_position[robot_id]
        self.robot_position[robot_id] = vertex
        self.robot_state[robot_id] = 'done'
        action_result = "(ActionResult\"" + self.actionID[robot_id] + "\"\"" + result + "\")"

        if move_type == 'Move':
            self.t_node[pre_position].pop(0)
            if not self.t_node[pre_position]:
                del self.t_node[pre_position]

            if not self.multipath[robot_id]:
                print('path finished!')
                self.send("agent://www.arbi.com/TaskManager", action_result)
        else:
            if move_type == 'Enter':
                self.t_node[pre_position].pop(0)
                if not self.t_node[pre_position]:
                    del self.t_node[pre_position]
            self.send("agent://www.arbi.com/TaskManager", action_result)
            print('\nif enter or exit')
            print(action_result)

        for k, v in self.t_node.items():
            print(k, v)
        for k, v in self.multipath.items():
            print(k, v)

    def on_request(self, sender: str, request: str) -> str:
        print("\nON REQUEST")
        print("sender : " + sender)
        print("on request : " + request)
        self.request_queue.append(generalized_list_factory.new_gl_from_gl_string(request))
        return "(ok)"

    def navigate_single_step(self, robot_id, end_vertex):
        robot_pos = self.robot_position[robot_id]
        if robot_pos is None:
            robot_pos = self.retrieve_robot_at(robot_id)
        path = "\"(Path " + str(robot_pos) + " " + str(end_vertex) + "))"
        move_msg = "(RequestMove \"" + robot_id + "+Move_" + end_vertex + "\"\"" + robot_id + path
        print('single step query :', move_msg)
        self.request("agent://www.arbi.com/TaskManager", move_msg)

    def send_enter_exit_msg(self, gl_msg, action):
        robot_id, move_type, vertex, direction = self.msg_parser(gl_msg, [1, 2, 3, 4])
        tail = "\"\"" + robot_id + "\"" + vertex + "\"" + direction + "\")"
        request_msg = "(Request" + move_type + " \"" + robot_id + action + tail
        self.request("agent://www.arbi.com/TaskManager", request_msg)
        self.actionID[robot_id] = gl_msg.get_expression(0).as_value().string_value()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    else:
        ip = "tcp://192.168.100.10:61316"
        # ip = "tcp://172.16.165.141:61316"
        # ip = "tcp://127.0.0.1:61316"
    nc = NavigationController(ip)
    while True:
        pass
