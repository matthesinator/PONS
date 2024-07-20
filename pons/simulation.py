import time
from typing import List, Dict

from pons.event_log import event_log, open_log, close_log, is_logging
import pons.event_log
import simpy

import pons
from pons.node import Node
from pons.event_log import event_log


class NetSim(object):
    """A network simulator."""

    def __init__(
        self,
        duration: int,
        world,
        nodes: List[Node],
        movements=[],
        msggens=None,
        config={},
    ):
        self.env = simpy.Environment()
        self.duration = duration
        # convert list from Node to dict with id as key
        self.nodes = {n.id: n for n in nodes}
        # self.nodes = nodes
        self.world = world
        self.movements = movements
        self.msggens = msggens
        self.config = config

        self.net_stats = {"tx": 0, "rx": 0, "drop": 0, "loss": 0}
        self.routing_stats = {
            "created": 0,
            "delivered": 0,
            "dropped": 0,
            "hops": 0,
            "latency": 0.0,
            "started": 0,
            "relayed": 0,
            "removed": 0,
            "aborted": 0,
            "dups": 0,
            "latency_avg": 0.0,
            "delivery_prob": 0.0,
            "hops_avg": 0.0,
            "overhead_ratio": 0.0,
        }
        self.router_stats = {}

        self.mover = pons.OneMovementManager(self.env, self.nodes, self.movements)

    def start_movement_logger(self, interval=1.0):
        """Start a movement logger."""
        print("start movement logger1")
        while True:
            yield self.env.timeout(interval)
            print("time: %d" % self.env.now)
            for node in self.nodes:
                print(node)

    def start_peers_logger(self, interval=1.0):
        """Start a peers logger."""
        print("start peers logger1")
        while True:
            yield self.env.timeout(interval)
            print("time: %d" % self.env.now)
            for node in self.nodes.values():
                print(node.neighbors)

    def setup(self):
        print("initialize simulation: ", self.config)

        if self.movements is not None and len(self.movements) > 0:
            print("-> start movement manager")
            self.mover.start()

        if self.config is not None:
            if self.config.get("movement_logger", True):
                self.env.process(self.start_movement_logger())

            if self.config.get("peers_logger", True):
                self.env.process(self.start_peers_logger())

            if self.config.get("event_logging", False):
                open_log()

            pons.event_log.event_filter = self.config.get("event_filter", [])

        for n in self.nodes.values():
            # print("-> start node %d w/ %d apps" % (n.id, len(n.apps)))
            n.start(self)

        if self.msggens is not None:
            for msggen in self.msggens:
                if (
                    "type" not in msggen.keys()
                    or msggen["type"] is None
                    or msggen["type"] == "single"
                ):
                    self.env.process(pons.message_event_generator(self, msggen))
                elif msggen["type"] == "burst":
                    self.env.process(pons.message_burst_generator(self, msggen))
                else:
                    raise Exception("unknown message generator type")

        print(self.nodes)
        for n in self.nodes.values():
            n.calc_neighbors(0, self.nodes.values())

    def using_contactplan(self):
        for n in self.nodes.values():
            for net in n.net.values():
                if net.contactplan is not None:
                    return True
        return False

    def contact_logger(self, contactplan):
        """Start a contact logger."""
        if not is_logging():
            return
        print("start contact logger: ", type(contactplan))
        if contactplan is None:
            print("No contact plan")
            return
        next_event = contactplan.next_event(0)
        if next_event is None:
            print("No events in contact plan")
            return

        total = 0
        while True:
            yield self.env.timeout(next_event)
            total += next_event
            events = contactplan.at(total)
            # print(len(events), "events at", total, ":", events)
            for e in events:
                if e.timespan[0] == total:
                    event_log(total, "LINK", {"event": "UP", "nodes": e.nodes})
                if e.timespan[1] == total:
                    event_log(total, "LINK", {"event": "DOWN", "nodes": e.nodes})

            next_event = contactplan.next_event(total)
            if next_event is None or next_event > self.duration:
                break
            next_event -= total

    def run(self):
        print("== running simulation for %d seconds ==" % self.duration)

        all_contactplans = set()

        for n in self.nodes.values():
            event_log(
                0,
                "CONFIG",
                {
                    "event": "START",
                    "id": n.id,
                    "x": n.x,
                    "y": n.y,
                    "capacity": n.router.capacity,
                    "used": n.router.used,
                },
            )
            for net in n.net.values():
                net.start(self)
                if net.contactplan is not None and net.contactplan.contacts is not None:
                    all_contactplans.add(net.contactplan.contacts)

        for cp in all_contactplans:
            print(cp)
            self.env.process(self.contact_logger(cp))
        print("global number of unique contact plans: ", len(all_contactplans))

        start_real = time.time()
        last_real = start_real
        last_sim = 0.0

        if not self.using_contactplan():
            now_sim = self.env.now
            for n in self.nodes.values():
                n.calc_neighbors(now_sim, self.nodes.values())
        else:
            for n in self.nodes.values():
                n.add_all_neighbors(self.env.now, self.nodes.values())

        while self.env.now < self.duration + 1.0:
            # self.env.run(until=self.duration)
            now_sim = self.env.now
            next_stop = min(self.duration + 1.0, now_sim + 5.0)
            self.env.run(until=next_stop)
            now_real = time.time()
            diff = now_real - last_real
            if diff > 60:
                rate = (now_sim - last_sim) / diff
                print(
                    "simulated %d seconds in %d seconds (%.2f x real time)"
                    % (now_sim - last_sim, diff, rate)
                )
                print(
                    "real: %f, sim: %d rate: %.02f steps/s"
                    % (now_real - start_real, now_sim, rate)
                )
                last_real = now_real
                last_sim = now_sim

        # self.env.run(until=self.duration)
        now_real = time.time()
        diff = now_real - start_real
        now_sim = self.env.now

        if diff > 0:
            rate = (now_sim) / diff
        else:
            rate = 0.0

        print("\nsimulation finished")
        print(
            "simulated %d seconds in %.02f seconds (%.2f x real time)"
            % (now_sim, diff, rate)
        )
        print("real: %f, sim: %d rate: %.02f steps/s" % (diff, now_sim, rate))

        if self.routing_stats["delivered"] > 0:
            self.routing_stats["latency_avg"] = (
                self.routing_stats["latency"] / self.routing_stats["delivered"]
            )
            self.routing_stats["hops_avg"] = (
                self.routing_stats["hops"] / self.routing_stats["delivered"]
            )
            self.routing_stats["overhead_ratio"] = (
                self.routing_stats["relayed"] - self.routing_stats["delivered"]
            ) / self.routing_stats["delivered"]
        if self.routing_stats["created"] > 0:
            self.routing_stats["delivery_prob"] = (
                self.routing_stats["delivered"] / self.routing_stats["created"]
            )
        else:
            self.routing_stats["delivery_prob"] = 0.0

        # delete entry "hops" and "latency" from routing_stats as they are only used for calculating the average
        del self.routing_stats["hops"]
        del self.routing_stats["latency"]

        close_log()
