# Changelog

## [1.3.0](https://github.com/bendikro/supervisord-dependent-startup/releases/tag/v1.3.0) - _2019-05-22_
[Commit history](https://github.com/bendikro/supervisord-dependent-startup/compare/v1.2.0...v1.3.0)

### Added
- Support for supervisor version 4 which now runs on python 3
- Add support for running as a module: `python3 -m supervisord_dependent_startup`
- Add support for installing source distribution with pip and upload to pypi


## [1.2.0](https://github.com/bendikro/supervisord-dependent-startup/releases/tag/v1.2.0) - _2018-06-04_
[Commit history](https://github.com/bendikro/supervisord-dependent-startup/compare/v1.1.0...v1.2.0)

### Bug fixes
- Do not attempt to start a process that has reached the FATAL state


## [1.1.0](https://github.com/bendikro/supervisord-dependent-startup/releases/tag/v1.1.0) - _2018-03-07_
[Commit history](https://github.com/bendikro/supervisord-dependent-startup/compare/v1.0.0...v1.1.0)

### Added
- Support for environment variable expansion in service config files


## [1.0.0](https://github.com/bendikro/supervisord-dependent-startup/releases/tag/v1.0.0) - _2018-01-03_
[Commit history](https://github.com/bendikro/supervisord-dependent-startup/compare/54e32080e673f1548c5d97ed483805d63754656a...v1.0.0)

#### Initial release of supervisord_dependent_startup
The plugin code is based on [ordered-startup-supervisord](https://github.com/jasoncorbett/ordered-startup-supervisord/)

### Added
- Support for starting supervisor services after given services reaches certain states
- Unit tests
- Command line arguments parsing with argparse
