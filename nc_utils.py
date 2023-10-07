import sys
import pathlib

sys.path.append("/home/kist/pythonProject/Python-mcArbiFramework")
sys.path.append("/home/uosai/pythonProject/Python-mcArbiFramework")

from arbi_agent.ltm.data_source import DataSource
from arbi_agent.model import generalized_list_factory


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
    print(str(result))
    return result


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
                    if self.nc.robot_state[robot_id] in ['entering', 'exiting', 'entered', 'exited']:
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
