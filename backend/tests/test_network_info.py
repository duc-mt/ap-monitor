from __future__ import annotations

from app.monitoring.network_info import parse_default_gateway_windows

ROUTE_PRINT = """
===========================================================================
Interface List
 12...3c 58 c2 11 22 33 ......Intel(R) Wi-Fi 6 AX201 160MHz
  1...........................Software Loopback Interface 1
===========================================================================

IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.56.1    192.168.56.10    281
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.42     45
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
      192.168.1.0    255.255.255.0         On-link      192.168.1.42    301
===========================================================================
"""


def test_windows_gateway_is_the_lowest_metric_default_route():
    assert parse_default_gateway_windows(ROUTE_PRINT) == "192.168.1.1"


def test_windows_gateway_is_none_without_a_default_route():
    assert parse_default_gateway_windows("IPv4 Route Table\n  127.0.0.0  255.0.0.0  On-link  127.0.0.1  331\n") is None
