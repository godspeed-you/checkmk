#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2021 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from logging import Logger
from threading import Lock
from typing import Any, Dict, List

from livestatus import LivestatusColumn, LocalConnection

#.
#   .--Host config---------------------------------------------------------.
#   |          _   _           _                      __ _                 |
#   |         | | | | ___  ___| |_    ___ ___  _ __  / _(_) __ _           |
#   |         | |_| |/ _ \/ __| __|  / __/ _ \| '_ \| |_| |/ _` |          |
#   |         |  _  | (_) \__ \ |_  | (_| (_) | | | |  _| | (_| |          |
#   |         |_| |_|\___/|___/\__|  \___\___/|_| |_|_| |_|\__, |          |
#   |                                                      |___/           |
#   +----------------------------------------------------------------------+
#   | Manages the configuration of the hosts of the local monitoring core. |
#   | It fetches and caches the information during runtine of the EC.      |
#   '----------------------------------------------------------------------'


class HostConfig:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger
        self._lock = Lock()
        self._hosts_by_name: Dict[str, Dict[str, Any]] = {}
        self._hosts_by_designation: Dict[str, str] = {}
        self._cache_timestamp = -1  # sentinel, always less than a real timestamp

    def get_config_for_host(self, host_name, deflt):
        with self._lock:
            if not self._update_cache_after_core_restart():
                return deflt

            return self._hosts_by_name.get(host_name, deflt)

    def get_canonical_name(self, event_host_name: str) -> str:
        with self._lock:
            if not self._update_cache_after_core_restart():
                return ""

            return self._hosts_by_designation.get(event_host_name.lower(), "")

    def _update_cache_after_core_restart(self) -> bool:
        """Once the core reports a restart update the cache

        Returns:
            False in case the update failed, otherwise True.
        """
        try:
            timestamp = self._get_config_timestamp()
            if timestamp > self._cache_timestamp:
                self._update_cache()
                self._cache_timestamp = timestamp
        except Exception:
            self._logger.exception("Failed to get host info from core. Try again later.")
            return False
        return True

    def _update_cache(self) -> None:
        self._logger.debug("Fetching host config from core")
        self._hosts_by_name.clear()
        self._hosts_by_designation.clear()
        for host in self._get_host_configs():
            host_name = host["name"]
            self._hosts_by_name[host_name] = host
            # Note: It is important that we use exactly the same algorithm here as
            # in the core, see World::loadHosts and World::getHostByDesignation.
            if host["address"]:
                self._hosts_by_designation[host["address"].lower()] = host_name
            if host["alias"]:
                self._hosts_by_designation[host["alias"].lower()] = host_name
            self._hosts_by_designation[host_name.lower()] = host_name
        self._logger.debug("Got %d hosts from core" % len(self._hosts_by_name))

    def _get_host_configs(self) -> List[Dict[str, Any]]:
        return LocalConnection().query_table_assoc(
            "GET hosts\n"
            "Columns: name alias address custom_variables contacts contact_groups")

    def _get_config_timestamp(self) -> LivestatusColumn:
        return LocalConnection().query_value("GET status\n"  #
                                             "Columns: program_start")
