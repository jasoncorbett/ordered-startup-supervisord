from __future__ import print_function

import collections
import logging

from . import Service, ServiceOptions, ServicesHandler, common
from .utils import cprint, plugin_logger_name, plugin_tests_logger_name  # noqa: F401

logger = logging.getLogger(plugin_tests_logger_name)


class SortOrderTestsBase(common.DependentStartupSupervisorTestsBase):

    def setUp(self):
        super(SortOrderTestsBase, self).setUp()
        self.handler = ServicesHandler(None, None)
        self.services = self.handler._services

    def get_sorted_services(self):
        return self.handler.get_sorted_services_list()

    def setup_services(self, services):
        if type(services) == str:
            services = [services]

        for name in services:
            p = Service(self.handler)
            p.name = name
            p.options = ServiceOptions()
            p.options.opts['dependent_startup'] = True
            p.options.opts['autostart'] = False
            self.services[name] = p

    def set_service_opts(self, name, depends=None, priority=None, inherit_priority=None):
        options = self.services[name].options
        if depends:
            for k in depends:
                options.wait_for_services[k] = depends[k]

        if priority is not None:
            options.opts['priority'] = priority

        if inherit_priority is not None:
            options.opts[ServiceOptions.inherit_priority_opts_string] = inherit_priority


Priorites = collections.namedtuple('Priorites', 'priority effective sort')


def get_priority(priority=None, effective=None, sort=Service.default_priority_sort):
    return Priorites(priority=priority, effective=effective, sort=sort)


class ServicePriorityTests(SortOrderTestsBase):

    def get_priorities(self, name):
        service = self.handler._services[name]
        return Priorites(priority=service.priority, effective=service.priority_effective,
                         sort=service.priority_sort)

    def test_service_with_default_priority(self):
        service = 'consul1'
        self.setup_services(service)
        priorites = self.get_priorities(service)
        expected = get_priority()
        self.assertEqual(expected, priorites)

    def test_service_with_dependent_priority_without_inherit(self):
        services = ['consul1', 'consul2']
        priority = 100
        self.setup_services(services)
        self.set_service_opts('consul1', priority=priority)
        self.set_service_opts('consul2', depends={'consul1': ['RUNNING']})
        priorites = self.get_priorities('consul2')
        expected = get_priority()
        self.assertEqual(expected, priorites)

    def test_service_with_priority(self):
        service = 'consul1'
        priority = 100
        self.setup_services(service)
        self.set_service_opts(service, priority=priority)
        priorites = self.get_priorities(service)
        expected = get_priority(priority=priority, effective=priority, sort=priority)
        self.assertEqual(expected, priorites)

    def test_service_with_inheritet_priority(self):
        services = ['consul1', 'consul2']
        priority = 100
        self.setup_services(services)
        self.set_service_opts('consul1', priority=priority)
        self.set_service_opts('consul2', depends={'consul1': ['RUNNING']}, inherit_priority=True)
        priorites = self.get_priorities('consul2')
        expected = get_priority(effective=priority, sort=priority)
        self.assertEqual(expected, priorites)


class SortOrderTests(SortOrderTestsBase):

    def test_service_sort_order_by_name(self):
        services = ['consul2', 'consul1']
        self.setup_services(services)
        ordered = self.get_sorted_services()
        self.assertEqual(ordered, sorted(services))

    def test_service_sort_by_priority(self):
        services = ['consul2', 'consul1']
        self.setup_services(services)
        self.set_service_opts('consul2', priority=100)
        ordered = self.get_sorted_services()
        self.assertEqual(ordered, services)

    def test_service_sort_by_dependency(self):
        services = ['consul2', 'consul1']
        self.setup_services(services)
        self.set_service_opts('consul2', depends={'consul1': ['RUNNING']}, priority=100)
        ordered = self.get_sorted_services()
        self.assertEqual(sorted(services), ordered)

    def test_sort_by_dependency_where_two_have_the_same_dependency(self):
        services = ['consul', 'consul2', 'consul1']
        self.setup_services(services)
        # consul1 and consul2 have the same dependcy, and is therefore sorted by name
        self.set_service_opts('consul1', depends={'consul': ['RUNNING']})
        self.set_service_opts('consul2', depends={'consul': ['RUNNING']})
        ordered = self.get_sorted_services()
        self.assertEqual(sorted(services), ordered)

    def test_sort_by_dependency_where_two_have_the_same_dependency_but_different_priority(self):
        services = ['consul', 'consul2', 'consul1']
        self.setup_services(services)
        # consul1 and consul2 have the same dependcy, but consul2 has lower priority so comes before
        self.set_service_opts('consul1', depends={'consul': ['RUNNING']})
        self.set_service_opts('consul2', depends={'consul': ['RUNNING']}, priority=100)
        ordered = self.get_sorted_services()
        self.assertEqual(services, ordered)

    def test_sort_by_dependency_where_two_have_the_same_dependency_but_one_inherits_priority_from_dependency(self):
        services = ['consul', 'consul2', 'consul1']
        self.setup_services(services)
        # consul1 and consul2 have the same dependcy, but consul2 inherits lower priority from consul so comes before
        self.set_service_opts('consul', priority=100)
        self.set_service_opts('consul1', depends={'consul': ['RUNNING']})
        self.set_service_opts('consul2', depends={'consul': ['RUNNING']}, inherit_priority=True)
        ordered = self.get_sorted_services()
        self.assertEqual(services, ordered)

    def test_sort_by_dependency_where_two_have_the_same_dependency_but_one_inherits_priority_and_one_has_custom(self):
        services = ['consul', 'consul2', 'consul1']
        self.setup_services(services)
        # consul1 and consul2 have the same dependcy, but consul2 inherits lower priority from consul so comes before
        self.set_service_opts('consul', priority=100)
        self.set_service_opts('consul1', depends={'consul': ['RUNNING']}, priority=99)
        self.set_service_opts('consul2', depends={'consul': ['RUNNING']}, inherit_priority=True)
        ordered = self.get_sorted_services()
        # consul1's prioriyty 99 is lower than consul2's inheritet priority 100
        self.assertEqual(sorted(services), ordered)


class SortOrderMultipleDependenciesTests(SortOrderTestsBase):

    def setUp(self):
        super(SortOrderMultipleDependenciesTests, self).setUp()
        # Define in reverse sort order to ensure sorting is necessary
        services = sorted(['consul', 'consul3', 'slurmd', 'consul2', 'slurmd2', 'slurmd3', 'slurmd4'], reverse=True)
        self.setup_services(services)

        self.set_service_opts('consul2', depends={'consul': ['RUNNING']})
        self.set_service_opts('consul3', depends={'consul': ['RUNNING'], 'consul2': ['RUNNING']})
        self.set_service_opts('slurmd', depends={'consul': ['RUNNING']})
        self.set_service_opts('slurmd2', depends={'consul': ['RUNNING'], 'slurmd': ['RUNNING']})
        self.set_service_opts('slurmd3', depends={'consul': ['RUNNING'], 'slurmd': ['RUNNING']})
        self.set_service_opts('slurmd4', depends={'consul': ['RUNNING'], 'slurmd': ['RUNNING']})

    def test_sort_default(self):
        ordered = self.get_sorted_services()
        # Each line is grouped by dependency tree level
        expected = [
            # 1: No dependencies
            'consul',
            # 2: sorted by name
            'consul2', 'slurmd',
            # 3: sorted by name
            'consul3', 'slurmd2', 'slurmd3', 'slurmd4']

        self.assertEqual(expected, ordered)

    def test_sort_with_priority_in_level_two(self):
        self.set_service_opts('slurmd', priority=100)
        ordered = self.get_sorted_services()
        # Each line is grouped by dependency tree level
        expected = [
            # 1: No dependencies
            'consul',
            # 2: sorted by priority (slurmd has lowest)
            'slurmd', 'consul2',
            # 3: sorted by name
            'consul3', 'slurmd2', 'slurmd3', 'slurmd4']
        self.assertEqual(expected, ordered)

    def test_sort_with_priority_in_level_three(self):
        self.set_service_opts('slurmd2', priority=100)
        ordered = self.get_sorted_services()
        # Each line is grouped by dependency tree level
        expected = [
            # 1: No dependencies
            'consul',
            # 2: sorted by name
            'consul2', 'slurmd',
            # 3: slurmd2 has lowest priority, rest sorted by name
            'slurmd2', 'consul3', 'slurmd3', 'slurmd4']
        self.assertEqual(expected, ordered)

    def test_sort_with_priority_in_level_two_and_inheritet_priority_in_level_three(self):
        self.set_service_opts('slurmd', priority=100)
        self.set_service_opts('slurmd2', inherit_priority=True)
        ordered = self.get_sorted_services()
        # Each line is grouped by dependency tree level
        expected = [
            # 1: No dependencies
            'consul',
            # 2: sorted by priority (slurmd has lowest)
            'slurmd', 'consul2',
            # 3: slurmd2 has lowest priority, inheritet from slurm
            'slurmd2', 'consul3', 'slurmd3', 'slurmd4']
        self.assertEqual(expected, ordered)

    def test_sort_with_priority_in_level_two_and_both_inheritet_and_manual_priorities_in_level_three(self):
        self.set_service_opts('slurmd', priority=100)
        self.set_service_opts('slurmd2', inherit_priority=True)
        self.set_service_opts('slurmd4', priority=99)
        ordered = self.get_sorted_services()
        # Each line is grouped by dependency tree level
        expected = [
            # 1: No dependencies
            'consul',
            # 2: sorted by priority (slurmd has lowest)
            'slurmd', 'consul2',
            # 3: slurmd4 has lowest priority (99),
            #    slurmd2 has second lowest priority inheritet from slurm, rest by name
            'slurmd4', 'slurmd2', 'consul3', 'slurmd3']
        self.assertEqual(expected, ordered)
