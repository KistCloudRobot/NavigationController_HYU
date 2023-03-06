import sys
import time

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.ltm.data_source import DataSource
from arbi_agent.agent import arbi_agent_executor
from arbi_agent.model import generalized_list_factory


def msg_parser(navigate_msg, c):
    return [navigate_msg.get_expression(i).as_value().string_value() for i in c]


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
        print(f'on notify : {notification}')


class NCBase(ArbiAgent):
    def __init__(self, broker_host, broker_port, broker_type):
        super().__init__()
        arbi_agent_executor.execute(broker_host=broker_host, broker_port=broker_port,
                                    agent_name="agent://www.arbi.com/NavigationController",
                                    agent=self, broker_type=broker_type, daemon=False)
        self.ds = NCDataSource(self)
        self.ds.connect(broker_host, broker_port, "ds://www.arbi.com/NavigationController", broker_type)
        self.node_queue = {}
        with open("../MultiAgentPathFinder/map_parse/map_cloud.txt", "r") as map_info:
            info_str = map_info.read()
            for line in info_str.split('\n'):
                target = line.split(' ')
                if target[0] == '\tname':
                    self.node_queue[target[1]] = []

    def retrieve_robot_at(self, robot_id):
        query = f'(context (robotAt"{robot_id}"$v1 $v2))'
        while True:
            query_result = self.ds.retrieve_fact(query)
            if query_result == '(error)':
                print(f'Waiting for robot Info {robot_id}...')
                time.sleep(1)
            else:
                gl_query_result = generalized_list_factory.new_gl_from_gl_string(query_result)
                result = gl_query_result.get_expression(0).as_generalized_list()
                return str(result.get_expression(1).as_value().int_value())

    def print_fn(self, opt_num):
        print(opt_num)
        print(self.robot_state)
        print(self.robot_position)
        print(self.robot_nr_type)
        print(self.multipath)
