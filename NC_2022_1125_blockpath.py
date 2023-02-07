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

# broker_host = "127.0.0.1"
# broker_host = "192.168.100.10"
broker_host = "172.16.165.143"
# broker_host = "192.168.100.10"
broker_port = 61316
broker_type = BrokerType.ACTIVE_MQ
# broker_type = BrokerType.ZERO_MQ


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
        self.actionID = {}
        self.robot_state = {}
        self.multipath = {}
        self.robot_position = {}
        self.t_node = {}
        # self.robot_list = ["AMR_LIFT1", "AMR_LIFT2", "AMR_LIFT3", "AMR_LIFT4"]
        self.robot_list = ["AMR_LIFT1", "AMR_LIFT2"]
        #########################################
        self.block_constant = 6  # This value should be more than 1. (2, 3, 4, ~)
        self.robot_path_block = {}

        #########################################
        for idx, r in enumerate(self.robot_list):
            self.actionID[r] = str()
            self.robot_state[r] = 'done'
            self.multipath[r] = list()
            self.robot_position[r] = self.retrieve_robot_at(r)
            self.t_node[self.robot_position[r]] = [r]
            self.robot_path_block[r] = []
        while True:
            time.sleep(1)
            if len(self.request_queue) == len(self.robot_list):
                break

        while True:
            time.sleep(1.0)
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
        query = "(context (robotAt \"" + robot_id + "\" $v1 $v2))"
        while True:
            query_result = self.ds.retrieve_fact(query)
            if query_result == "(error)":
                print("Waiting for robot Info " + str(robot_id) + "...")
                time.sleep(1)
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
        print("pathfinder request :", request_msg)
        response = self.request("agent://www.arbi.com/MultiAgentPathFinder", request_msg)
        print("pathfinder response :", response)
        response_gl = generalized_list_factory.new_gl_from_gl_string(response)
        multipath = {}
        for idx, r in enumerate(self.robot_list):
            temp_gl = response_gl.get_expression(idx).as_generalized_list()
            path = str(temp_gl.get_expression(1))[:-1]
            temp_split = path.split(' ')
            multipath[r] = temp_split[2:]

        self.reduce_t_node(multipath)

    def reduce_t_node(self, multipath):
        print('multipath result')
        for k, v in multipath.items():
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

        for r in self.robot_list:
            if self.multipath[r] and self.multipath[r][0] == self.robot_position[r]:
                self.multipath[r] = dc(self.multipath[r][1:])

    def run(self):
        if self.request_queue:
            for i in range(len(self.request_queue)):
                navigateMsg = dc(self.request_queue[i])
                glName = navigateMsg.get_name()
                actionID, robotID, start_vertex, end_vertex = self.msg_parser(navigateMsg, [0, 1, 2, 3])
                if glName == "RequestEnterToStation":
                    self.request_queue.pop(i)
                    self.robot_state[robotID] = 'moving'
                    self.send_enter_exit_msg(navigateMsg, "+Enter")
                    break

            else:
                navigateMsg = dc(self.request_queue[0])
                glName = navigateMsg.get_name()
                actionID, robotID, start_vertex, end_vertex = self.msg_parser(navigateMsg, [0, 1, 2, 3])
                if glName == "RequestExitFromStation":
                    if end_vertex not in self.t_node.keys() or not self.t_node[end_vertex]:
                        self.request_queue.pop(0)
                        self.robot_state[robotID] = 'moving'
                        self.send_enter_exit_msg(navigateMsg, "+Exit")
                        self.t_node[end_vertex] = [robotID]

                elif glName == "RequestNavigate":
                    pop_flag = True
                    for s in self.robot_state.values():
                        if s == 'moving':
                            pop_flag = False
                            break
                    if pop_flag:
                        print('pop occurs')
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

        waiting_nav = False
        for i in range(len(self.request_queue)):
            if self.request_queue[i].get_name() == "RequestNavigate":
                waiting_nav = True
                break

        #(._)
        if not waiting_nav:
            # print('not waiting_nav')
            for robot_name in self.robot_list:
                if self.multipath[robot_name] and (self.robot_state[robot_name] == 'done'):
                    if self.t_node[self.multipath[robot_name][0]][0] == robot_name:
                        block_len = 1
                        temp_set = [self.robot_position[robot_name], self.multipath[robot_name][0]]
                        for idx in range(1, min(self.block_constant, len(self.multipath[robot_name]))):
                            temp_node = self.multipath[robot_name][idx]
                            if self.t_node[temp_node][0] == robot_name and temp_node not in temp_set:
                                block_len = idx + 1
                                temp_set.append(temp_node)
                            else:
                                break
                        print('block_len', block_len)
                        path_block = dc(self.multipath[robot_name][0:block_len])
                        self.multipath[robot_name] = dc(self.multipath[robot_name][block_len:])
                        self.robot_path_block[robot_name] = dc(path_block)
                        self.navigate_single_step(robot_name, path_block)
                        self.robot_state[robot_name] = 'moving'

    def on_data(self, sender: str, data: str):
        print("\nON DATA")
        print("sender : " + sender)
        print("on data : " + data)
        print('pre_position', self.robot_position)
        gl_msg = generalized_list_factory.new_gl_from_gl_string(data)
        action_id, result = self.msg_parser(gl_msg, [0, 1])
        robot_id, move_type, _ = self.action_parser(action_id)
        pre_position = self.robot_position[robot_id]
        self.robot_position[robot_id] = self.retrieve_robot_at(robot_id)
        self.robot_state[robot_id] = 'done'
        action_result = "(ActionResult\"" + self.actionID[robot_id] + "\"\"" + result + "\")"

        print('Action-ID')
        for k, v in self.actionID.items():
            print(k, v)

        if move_type == 'Move':
            if not self.t_node[pre_position]:
                print('Error, 1')
                exit()
            self.t_node[pre_position].pop(0)
            for pos in self.robot_path_block[robot_id][:-1]:
                if not self.t_node[pos]:
                    print('Error, 2')
                    exit()
                self.t_node[pos].pop(0)

            if not self.multipath[robot_id]:
                print('path finished!')
                print("send action result : " + str(action_result))
                self.send("agent://www.arbi.com/TaskManager", action_result)
        else:
            if move_type == 'Enter':
                print('[on data] enter t node : ' + str(self.t_node))
                print('[on data] enter pre position : ' + str(pre_position))
                if not self.t_node[pre_position]:
                    print('Error, 3')
                    exit()
                self.t_node[pre_position].pop(0)
            print("send action result : " + str(action_result))
            self.send("agent://www.arbi.com/TaskManager", action_result)
            print('\nif enter or exit')
            print(action_result)

        print('robot state', self.robot_state)
        print('curr_position', self.robot_position)
        for k, v in self.t_node.items():
            if v:
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
        temp = ''
        for v in end_vertex:
            temp += (str(v) + ' ')
        temp = temp[:-1]
        current_pos = self.retrieve_robot_at(robot_id)
        # while len(str(current_pos)) < 3:
        #     time.sleep(0.1)
        #     current_pos = self.retrieve_robot_at(robot_id)
        #     print("current pos :", str(current_pos))
        print("navigate single step robot id: ", str(robot_id))
        print('navigate single step robot current pos: ', str(current_pos))
        path = "\"(Path " + current_pos + ' ' + temp + "))"

        print('single step query', current_pos, path)

        move_msg = "(RequestMove \"" + robot_id + "+Move_" + str(end_vertex[-1]) + "\"\"" + robot_id + path
        print(move_msg)
        if temp != self.robot_position[robot_id]:
            self.request("agent://www.arbi.com/TaskManager", move_msg)
        else:
            self.robot_state[robot_id] = 'done'
            print('code12')

    def send_enter_exit_msg(self, gl_msg, action):
        robot_id, move_type, vertex, direction = self.msg_parser(gl_msg, [1, 2, 3, 4])
        tail = "\"\"" + robot_id + "\"" + vertex + "\"" + direction + "\")"
        request_msg = "(Request" + move_type + " \"" + robot_id + action + tail
        self.request("agent://www.arbi.com/TaskManager", request_msg)
        self.actionID[robot_id] = gl_msg.get_expression(0).as_value().string_value()


if __name__ == '__main__' :
    nc = NavigationController(broker_host, broker_port)
    while True:
        pass
