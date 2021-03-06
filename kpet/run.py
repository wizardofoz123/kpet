# Copyright (c) 2019 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General Public
# License v.2 or later.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""Execution of tests from the database"""

import os
import jinja2
from lxml import etree
from kpet import data


class Suite:    # pylint: disable=too-few-public-methods
    """A test suite run"""

    def __init__(self, suite, cases):
        """
        Initialize a test suite run.

        Args:
            suite:          The suite to run.
            cases:          List of the suite's cases to run.
        """
        assert isinstance(suite, data.Suite)
        assert isinstance(cases, list)
        for case in cases:
            assert case in suite.cases

        self.description = suite.description
        self.tasks = suite.tasks
        self.ignore_panic = suite.ignore_panic
        self.hostRequires = suite.hostRequires  # pylint: disable=invalid-name
        self.partitions = suite.partitions
        self.kickstart = suite.kickstart
        self.cases = cases


class Host:     # pylint: disable=too-few-public-methods
    """A host running test suites"""

    # pylint: disable=redefined-builtin
    def __init__(self, type, suites):
        """
        Initialize a host run.

        Args:
            type:       Type of the host.
            suites:     List of suite runs to execute.
        """
        assert isinstance(type, data.HostType)
        assert isinstance(suites, list)
        for suite in suites:
            assert isinstance(suite, Suite)

        self.ignore_panic = type.ignore_panic
        # pylint: disable=invalid-name
        self.hostRequires = type.hostRequires
        self.partitions = type.partitions
        self.kickstart = type.kickstart
        self.tasks = type.tasks
        self.suites = suites


class Base:     # pylint: disable=too-few-public-methods
    """A specific execution of tests in a database"""

    @staticmethod
    def __get_hosts(database, target):
        """
        Get a list of hosts to run.

        Args:
            database:   The database to get test data from.
            target:     The target (a data.Target) to match/run tests against.
        """
        assert isinstance(database, data.Base)
        assert isinstance(target, data.Target)

        host_types = \
            database.host_types \
            if database.host_types is not None \
            else {"": data.DEFAULT_HOST_TYPE}

        # Build a pool of suites and cases
        pool_suites = []
        for suite in database.suites:
            if suite.matches(target):
                pool_cases = []
                for case in suite.cases:
                    if case.matches(target):
                        pool_cases.append(case)
                if pool_cases:
                    pool_suites.append((suite, pool_cases))

        # Distribute suites and their cases to hosts
        hosts = list()
        for host_type_name, host_type in host_types.items():
            # Create a suite run list
            suites = list()
            for pool_suite in pool_suites.copy():
                suite, pool_cases = pool_suite
                # Create case list from cases matching host type
                cases = []
                for case in pool_cases.copy():
                    host_type_regex = \
                        case.host_type_regex or \
                        suite.host_type_regex or \
                        database.host_type_regex
                    if database.host_types is None or \
                       host_type_regex and \
                       host_type_regex.match(host_type_name):
                        cases.append(case)
                        pool_cases.remove(case)
                # Add the suite run to the list, if it has cases to run
                if cases:
                    suites.append(Suite(suite, cases))
                # Remove suite from the pool, if it has no more cases
                if not pool_cases:
                    pool_suites.remove(pool_suite)
            # Add host to list, if it has suites to run
            if suites:
                hosts.append(Host(host_type, suites))

        return hosts

    def __init__(self, database, target):
        """
        Initialize a test run.

        Args:
            database:   The database to get test data from.
            target:     The target (a data.Target) to match/run tests against.
                        The target's tree must be present in the database.
        """
        assert isinstance(database, data.Base)
        assert isinstance(target, data.Target)
        assert target.trees <= set(database.trees.keys())
        # TODO Check architecture presence in database once it's added there
        self.database = database
        self.target = target
        self.hosts = self.__get_hosts(database, target)

    # pylint: disable=too-many-arguments
    def generate(self, description, kernel_location, lint):
        """
        Generate Beaker XML which would execute tests in the database.
        The target supplied at creation must have exactly one tree and exactly
        one architecture for this to succeed.

        Args:
            description:        The run description string.
            kernel_location:    Kernel location string (a tarball or RPM URL).
            lint:               Lint and reformat the XML output, if True.
        Returns:
            The beaker XML string.
        """
        assert isinstance(description, str)
        assert isinstance(kernel_location, str)
        assert len(self.target.trees) == 1
        assert len(self.target.arches) == 1

        tree_name = list(self.target.trees)[0]
        arch_name = list(self.target.arches)[0]

        params = dict(
            DESCRIPTION=description,
            KURL=kernel_location,
            ARCH=arch_name,
            TREE=tree_name,
            HOSTS=self.hosts,
            getenv=os.getenv,
        )

        jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([self.database.dir_path]),
            trim_blocks=True,
            keep_trailing_newline=True,
            lstrip_blocks=True,
            autoescape=jinja2.select_autoescape(
                enabled_extensions=('xml'),
                default_for_string=True,
            ),
        )
        template = jinja_env.get_template(self.database.trees[tree_name])
        text = template.render(params)

        if lint:
            parser = etree.XMLParser(remove_blank_text=True, encoding="utf-8")
            tree = etree.XML(text, parser)
            text = etree.tostring(tree, encoding="utf-8",
                                  xml_declaration=True,
                                  pretty_print=True).decode("utf-8")
        return text
