## Ping example

The following is an example of a supervisor configuration that starts one item
after the next in the order given by the depdency options. The order will be
`ping`, `sleep`, `ping2`, and `ping3`.

### supervisord.conf

Write the following to `/tmp/tmp_home/etc/supervisord.conf`

```INI
[unix_http_server]
file=/tmp/tmp_home/tmp/supervisor.sock

[supervisord]
logfile=/tmp/tmp_home/supervisord_logs/supervisord.log
loglevel=info
pidfile=///tmp/tmp_home/tmp/supervisord.pid
nodaemon=false
minfds=1024
minprocs=200

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///tmp/tmp_home/tmp/supervisor.sock ; use a unix:// URL  for a unix socket

[eventlistener:dependentstartup]
command=python3 /path/to/supervisord_dependent_startup/supervisord_dependent_startup.py -c /tmp/tmp_home/etc/supervisord.conf
stderr_logfile=/tmp/tmp_home/supervisord_logs/%(program_name)s-err.log
events=PROCESS_STATE
autostart=true
; The following settings are necessary to ensure the supervisord_dependent_startup
; process exits with EXITED when successfull, and FATAL when an error occured
autorestart=unexpected
startretries=0
exitcodes=0,3

[include]
files = /tmp/tmp_home/etc/supervisord.d/*.ini
```

### service configuration files

Next we will look at the jobs in the **supervisord.d** directory like **supervisord.d/ping.ini**:

#### ping.ini

Write to `/tmp/tmp_home/etc/supervisord.d/ping.ini`

```INI
[program:ping]
command=/bin/ping -c 1 www.google.com
redirect_stderr=true
autostart=false
startsecs=0
dependent_startup=true
```

#### ping2.ini

Write to `/tmp/tmp_home/etc/supervisord.d/ping2.ini`

```INI
[program:ping2]
command=/bin/ping -c 1 www.google.com
redirect_stderr=true
autostart=false
startsecs=0
dependent_startup=true
dependent_startup_wait_for=sleep:running
```

#### ping3.ini

Write to `/tmp/tmp_home/etc/supervisord.d/ping3.ini`

```INI
[program:ping3]
command=/bin/ping -c 1 www.google.com
redirect_stderr=true
autostart=false
startsecs=0
dependent_startup=true
dependent_startup_wait_for=ping2:exited
```

#### sleep.ini

Write to `/tmp/tmp_home/etc/supervisord.d/sleep.ini`

```INI
[program:sleep]
command=/bin/sleep 15
redirect_stderr=true
autostart=false
autorestart=true
startsecs=5
dependent_startup=true
dependent_startup_wait_for=ping:exited
```

## Ping example execution

Notice how all of the *program:* sections have autostart=false.  Finally let's look at the output of running
supervisord:

```Shell
$ supervisord  -c /tmp/tmp_home/etc/supervisord.conf -n
2018-03-02 05:20:22,975 INFO Included extra file "/tmp/tmp_home/etc/supervisord.d/ping.ini" during parsing
2018-03-02 05:20:22,975 INFO Included extra file "/tmp/tmp_home/etc/supervisord.d/ping2.ini" during parsing
2018-03-02 05:20:22,975 INFO Included extra file "/tmp/tmp_home/etc/supervisord.d/ping3.ini" during parsing
2018-03-02 05:20:22,975 INFO Included extra file "/tmp/tmp_home/etc/supervisord.d/sleep.ini" during parsing
2018-03-02 05:20:22,981 INFO RPC interface 'supervisor' initialized
2018-03-02 05:20:22,981 CRIT Server 'unix_http_server' running without any HTTP authentication checking
2018-03-02 05:20:22,981 INFO supervisord started with pid 11312
2018-03-02 05:20:23,983 INFO spawned: 'dependentstartup' with pid 11321
2018-03-02 05:20:25,075 INFO success: dependentstartup entered RUNNING state, process has stayed up for > than 1 seconds (startsecs)
2018-03-02 05:20:25,078 INFO spawned: 'ping' with pid 11323
2018-03-02 05:20:25,078 INFO success: ping entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
2018-03-02 05:20:25,100 INFO exited: ping (exit status 0; expected)
2018-03-02 05:20:25,104 INFO spawned: 'sleep' with pid 11325
2018-03-02 05:20:30,114 INFO success: sleep entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
2018-03-02 05:20:31,119 INFO spawned: 'ping2' with pid 11342
2018-03-02 05:20:31,120 INFO success: ping2 entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
2018-03-02 05:20:31,143 INFO exited: ping2 (exit status 0; expected)
2018-03-02 05:20:31,147 INFO spawned: 'ping3' with pid 11343
2018-03-02 05:20:31,147 INFO success: ping3 entered RUNNING state, process has stayed up for > than 0 seconds (startsecs)
2018-03-02 05:20:31,169 INFO exited: ping3 (exit status 0; expected)
2018-03-02 05:20:40,108 INFO exited: sleep (exit status 0; expected)
2018-03-02 05:20:41,112 INFO spawned: 'sleep' with pid 11374
2018-03-02 05:20:46,122 INFO success: sleep entered RUNNING state, process has stayed up for > than 5 seconds (startsecs)
```

All of the processes started in order. **ping2** started after sleep was
*RUNNING* (influenced by startsecs). When sleep respawned it didn't restart the
chain, it only goes through it once.
