# Dependency support when starting Supervisor services

`supervisord-dependent-startup` is a plugin for
[Supervisor](http://supervisord.org) that allows starting up services after
dependent services have reached specific states. This plugin is based on
[ordered-startup-supervisord](https://github.com/jasoncorbett/ordered-startup-supervisord/)
by [Jason Corbett](https://github.com/jasoncorbett).

## The Problem

The problem can be seen in [supervisor bug
#122](https://github.com/Supervisor/supervisor/issues/122). The priority order
in supervisor does determine startup order, but when `autostart=true` supervisor
doesn't wait for the previous process to be `RUNNING` in order to continue. What
is even harder is having initialization scripts that need to exit before
continuing. This software is meant to make this one use case easier.

## How it works

This is an event listener for supervisor. This means it is run by supervisor on
startup and supervisor will send it messages whenever a service reaches a
particular process state. When configured it will wait till a supervisor
subprocess gets to the configured state before starting dependent services.

## Caveats

The plugin does not start groups. It can start services that are part of a
group, but it won't directly start a group.

## Installing

```
# From pypi
pip install supervisord-dependent-startup

# From github:
pip install -e git+https://github.com/bendikro/supervisord-dependent-startup.git#egg=supervisord-dependent-startup
```

## Configuration

Configuration requires several things. First you need to configure
`supervisord-dependent-startup` in `supervisor.conf` as an event listener.

```INI
[eventlistener:dependentstartup]
command=python -m supervisord_dependent_startup
autostart=true
autorestart=unexpected
startretries=0
exitcodes=0,3
events=PROCESS_STATE
```

### Service configuration options

There are three configuration options for a service (`[program:*]`) to control
how it is processed by `supervisord-dependent-startup`

#### `dependent_startup`

Mark this service to be handled by `supervisord-dependent-startup`. This must be
set to `true` for all services that depend on other services or is being
depended on by other services.

| Type | **bool**
:--- | :---
| **Required** | **yes**
| **Note**     | When setting this to `true`, `autostart` *must* be set to `false`


#### `dependent_startup_wait_for`

Specify the services this service depends on before in can be started.

| Type | **str**
:--- | :---
| **Required**| **no**
| **Format**  | `dependent_startup_wait_for=<parent-service>:<state[,state[..]]> [..]`
| **Note**    | `state` must one or more comma separated values of:  `starting`, `running`, `backoff`, `stopping`, `exited`, `fatal`

###### Example with one dependency

To have a service named *child* depend on a service *parent*:
``dependent_startup_wait_for=parent:running``


###### Example with two dependencies

Multiple dependencies are separated by a white space. To have a service named
*child* depend on the services *parent1* and *parent2*:
``dependent_startup_wait_for=parent1:running parent2:running``

#### `dependent_startup_inherit_priority`

Specify if the service should inherit its priority from the services it depends
on.

| Type | **bool**
:--- | :---
| **Required**| **no**
| **Example** | ``dependent_startup_inherit_priority=true``


## Building and testing

#### Run tests

```Shell
python setup.py test
```

#### Create source dist

```Shell
python setup.py sdist
```

#### Run tests and code syntax check

```Shell
tox
```
