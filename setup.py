#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys

from setuptools import find_packages, setup
from setuptools.command.test import test as TestCommand  # noqa: N812

from supervisord_dependent_startup.__version import __version__


class PyTest(TestCommand):
    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = []

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


setup(
    name="supervisord-dependent-startup",
    description=("A plugin for Supervisor that allows starting up services after "
                 "dependent services have reached specific states. "
                 "Based on ordered-startup-supervisord by Jason Corbett"),
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    version=__version__,
    author='Bendik Rønning Opstad',
    author_email='bro.devel@gmail.com',
    license="Apache Software License v2",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 2.7",
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        "Topic :: System :: Boot :: Init",
        "Environment :: Plugins"
    ],
    packages=find_packages(),
    include_package_data=True,
    install_requires=open('requirements.txt').read().split("\n"),
    url="https://github.com/bendikro/supervisord-dependent-startup",
    tests_require=['supervisor', 'mock', 'pytest', 'testfixtures', 'jinja2', 'toposort', 'parameterized'],
    cmdclass={'test': PyTest},
    test_suite='supervisord_dependent_startup.tests',
    entry_points={
        "console_scripts": [
            "supervisord-dependent-startup=supervisord_dependent_startup.supervisord_dependent_startup:main"
        ]
    }
)
