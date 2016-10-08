#!/usr/bin/env python

__author__ = 'Jason Corbett'

from setuptools import setup, find_packages

setup(
    name="ordered-startup-supervisord",
    description="An event listener for supervisord that will start up items in order upon certain states.",
    version="1.0" + open("build.txt").read().strip(),
    license="Apache Software License v2",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 2.7",
        "Topic :: System :: Boot :: Init",
        "Environment :: Plugins"
    ],
    long_description=open('README.rst').read(),
    py_modules=['ordered_startup_supervisord'],
    #packages=find_packages(exclude=['distribute_setup']),
    #package_data={'': ['*.txt', '*.rst', '*.html']},
    #include_package_data=True,
    install_requires=open('requirements.txt').read().split("\n"),
    author="Jason Corbett",
    url="http://github.com/jasoncorbett/ordered-startup-supervisord",
    entry_points={
        "console_scripts": [
            "ordered-startup-listener=ordered_startup_supervisord:main"
        ]
    }
)
