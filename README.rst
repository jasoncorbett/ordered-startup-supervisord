=======================================
 Priority Order Startup for Supervisor
=======================================

The Problem
===========
The problem can be seen in `supervisor bug 122`_.  The priority order in supervisor does determine startup order, but
when **autostart=true** supervisor doesn't wait for the previous process to be RUNNING in order to continue.  What is
even harder is having initialization scripts that need to exit before continuing.  This software is meant to make
this one use case easier.

.. _supervisor bug 122: https://github.com/Supervisor/supervisor/issues/122

How it works
============

This is an event listener for supervisor.  This means it is run by supervisor on startup and supervisor will send it
messages whenever a program reaches a particular process state.  When configured it will wait till a supervisor
subprocess get's to the configured state, then starts the next process.  The next process is determined by priority.

Caveats
=======

This does not solve every situation.  If what you need is everything starting up one by one, then this will likely solve
your issue.  If you need to mix and match which starts in parallel and which in serial (dependencies) this is probably
not what you want.

This does not start groups.  It can start programs that are part of a group, but it won't directly start a group.

Configuration
=============

Configuration requires several things.  First you need to configure this software as a event listener::

    [eventlistener:inorder]
    command=/path/to/ordered-startup-listener
    autostart=true
    events=PROCESS_STATE

This is probably the only thing you want to autostart.  It needs xml rpc api, so don't forget to configure that.  A
full example is shown later.

There are 2 additional configurations that can be put in a *[program:* section.  These are:

    **startinorder**
      This must be set to *true* in order to have the next process in the line to be started after this one.
    **startnextafter**
      This is optional and is defaulted to *RUNNING*.  If you want the process to exit before continuing then set
      this to *EXITED* (this is useful for initialization scripts that have to finish before something else starts).
      This is case insensitive.

Example
=======

The following is an example of a supervisor configuration that starts one item after the next in priority order.
The order will be ping, sleep, ping2, and ping3.  The ping jobs are configured to wait till they have exited before
the next job is started (this is commonly used for initialization scripts that need to complete before continuing).

First **supervisord.conf**::

    [supervisord]
    nodaemon=true

    [inet_http_server]
    port=127.0.0.1:9001

    [supervisorctl]
    serverurl=http://127.0.0.1:9001

    [rpcinterface:supervisor]
    supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

    [eventlistener:inorder]
    command=/path/to/ordered-startup-listener
    autostart=true
    events=PROCESS_STATE

    [include]
    files=supervisord.d/*.conf

Next we will look at the jobs in the **supervisord.d** directory like **supervisord.d/ping.conf**::

    [program:ping]
    command=/sbin/ping -c1 www.google.com
    priority=100
    startsecs=0
    autorestart=false
    autostart=false
    startinorder=true
    startnextafter=exited

**supervisord.d/ping2.conf**::

    [program:ping2]
    command=/sbin/ping -c1 www.google.com
    priority=200
    startsecs=0
    autorestart=false
    autostart=false
    startinorder=true
    startnextafter=exited

**supervisord.d/ping3.conf**::

    [program:ping3]
    command=/sbin/ping -c1 www.google.com
    priority=400
    startsecs=0
    autorestart=false
    autostart=false
    startinorder=true
    startnextafter=exited

**supervisord.d/sleep.conf**::

    [program:sleep]
    command=/bin/sleep 60
    priority=101
    startsecs=5
    autorestart=true
    autostart=false
    startinorder=true

Notice how all of the *program:* sections have autostart=false.  Finally let's look at the output of running
supervisord::

    2016-10-08 12:15:22,014 INFO Increased RLIMIT_NOFILE limit to 1024
    2016-10-08 12:15:22,015 INFO Included extra file "/Users/jason.corbett/tmp/supervisor/supervisord.d/ping.conf" during parsing
    2016-10-08 12:15:22,015 INFO Included extra file "/Users/jason.corbett/tmp/supervisor/supervisord.d/ping2.conf" during parsing
    2016-10-08 12:15:22,015 INFO Included extra file "/Users/jason.corbett/tmp/supervisor/supervisord.d/ping3.conf" during parsing
    2016-10-08 12:15:22,015 INFO Included extra file "/Users/jason.corbett/tmp/supervisor/supervisord.d/sleep.conf" during parsing
    2016-10-08 12:15:22,044 INFO RPC interface 'supervisor' initialized
    2016-10-08 12:15:22,044 CRIT Server 'inet_http_server' running without any HTTP authentication checking
    2016-10-08 12:15:22,045 INFO supervisord started with pid 39396
    2016-10-08 12:15:23,050 INFO spawned: 'inorder' with pid 39402
    2016-10-08 12:15:23,325 INFO spawned: 'ping' with pid 39403
    2016-10-08 12:15:23,325 INFO success: ping entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
    2016-10-08 12:15:23,359 INFO exited: ping (exit status 0; expected)
    2016-10-08 12:15:24,048 INFO success: inorder entered RUNNING state, process has stayed up for > than 1 seconds (startsecs)
    2016-10-08 12:15:24,052 INFO spawned: 'sleep' with pid 39404
    2016-10-08 12:15:29,051 INFO success: sleep entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
    2016-10-08 12:15:29,055 INFO spawned: 'ping2' with pid 39410
    2016-10-08 12:15:29,056 INFO success: ping2 entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
    2016-10-08 12:15:29,069 INFO exited: ping2 (exit status 0; expected)
    2016-10-08 12:15:29,072 INFO spawned: 'ping3' with pid 39411
    2016-10-08 12:15:29,072 INFO success: ping3 entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
    2016-10-08 12:15:29,084 INFO exited: ping3 (exit status 0; expected)
    2016-10-08 12:16:24,059 INFO exited: sleep (exit status 0; expected)
    2016-10-08 12:16:24,061 INFO spawned: 'sleep' with pid 39452
    2016-10-08 12:16:29,059 INFO success: sleep entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)

All of the processes started in order.  **ping2** started after sleep was *RUNNING* (influenced by startsecs).  When
sleep respawned it didn't restart the chain, it only goes through it once.
