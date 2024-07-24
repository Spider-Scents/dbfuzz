# dbfuzz

This repository includes source code of ```dbfuzz```, the prototype implementation of our database-aware grey-box scanner for stored XSS, as well as Docker Compose setups for a subset of the evaluated web applications.

Running the scanner against a web application will produce a mapping from database columns to unprotected outputs where XSS payloads are executed.
These unprotected outputs are code smells that correspond to either dormant stored XSS or stored XSS vulnerabilities.

Manual analysis is required to determine the vulnerability and exploitability of unprotected outputs.

dbfuzz is the prototype implementation of [Spider-Scents: Grey-box Database-aware Web Scanning for Stored XSS](https://www.cse.chalmers.se/research/group/security/spider-scents/#).

This repository is licensed under the terms of the MIT license.

```
├── Breakage.py             # Breakage module
├── Browser.py              # Browser automation to capture cookies and login
├── Data.py                 # Data analysis functions
├── Database.py             # Database module
├── Helper.py               # Functions used throughout
├── Payload.py              # Payload module
├── Scanner.py              # Scanner module
├── blackwidow              # Black Widow code, used for scanner
│   ├── ...
├── cookie_extension        # Chrome extension for recording initial cookies
│   ├── ...
├── dbfuzz.py               # Main script
├── docker                  # Example web applications
│   ├── ...
└── meta.py                 # Post-processing analysis of results
```

# Environment

dbfuzz has been tested on Ubuntu 22.04 LTS, 24.04 LTS, and Mac OS Sonoma 14.5.

Instructions for setting up an environment on [Ubuntu 24.04](#ubuntu-environment) are provided, as well as a description of the [Mac](#mac-environment) environment.

# Requirements

dbfuzz is written in Python, and requires Chrome and [Chromedriver](https://googlechromelabs.github.io/chrome-for-testing/), mysql/mysqldump command, and graphviz.
Python library requirements are available in the Pipfile of this repository.

Example web applications, located in the docker folder, are run with Docker and Docker Compose.

# To scan a web application

## Install Python 3.10

Python 3.10 is specified, but other adjacent versions likely work (untested).

## Install MariaDB (or MySQL)

This is only needed for the script to execute the ```mysql``` and ```mysqldump``` commands to restore and backup databases.

## Install Chrome and ChromeDriver: https://chromedriver.chromium.org

## Install Graphviz

## Install Python packages: ```pipenv install```

## Launch your web application

Examples are included in the docker folder of this repository.

After extracting a given docker image from an example, correct the permissions of the ```dbfuzz``` directory served by Apache.
Otherwise, you will get a 403 - Forbidden response when accessing the web application examples.

```chmod 755 dbfuzz```

To launch any of these: ```docker compose up --build``` in the web application's subdirectory.

And then restore the database for the web application by logging into http://localhost:8080/ with:
- server: mariadb
- username: root
- password: notSecureChangeMe

After logging into phpMyAdmin, create the relevant database, then restore the provided backup.

For example, with the docker/doctor, in the phpMyAdmin interface, create database 'damsmsdb', then restore it with docker/doctor/damsmsdb.sql

## Create a configuration for the web application, with additional details such database and login credentials.

This can be based on config_sample.ini

Instructions are included in this file.

Note that you may have to update the cookies in the config file to allow the initial URL crawler to access authenticated pages, if they are not current.

The location of mysql and mysqldump, specified in this config, may also be different on your system.

Configurations are already included for each of the example web applications.

For example, docker/doctor has its configuration at docker/doctor/config_doctor.ini

## Then the scanner can be run with: ```pipenv run script --config 'webapp_config.ini'```

Alternatively, use the evaluation parameters:
```
pipenv run script  --config 'webapp_config.ini' --insert-empty --reset-fuzzing --reset-scanning --sensitive-rows --primary-keys --traversal column
```

In the first run, the script will stop for you to remove dangerous URLs.

Remove dangerous URLs, such as those that delete items or log out the user, manually.

For example, docker/doctor will produce a file 'urls\ doctor\ app_config.insert_empty=True.txt' containing
```
["http://localhost/dams/doctor/dashboard.php", "http://localhost/dams/", "http://localhost/dams/doctor/search.php", "http://localhost/dams/doctor/search.php#", "http://localhost/dams/doctor/profile.php", "http://localhost/dams/doctor/profile.php#", "http://localhost/dams/doctor/dashboard.php#", "http://localhost/dams/doctor/all-appointment.php", "http://localhost/dams/doctor/change-password.php", "http://localhost/dams/doctor/new-appointment.php", "http://localhost/dams/doctor/change-password.php#", "http://localhost/dams/doctor/new-appointment.php#", "http://localhost/dams/doctor/all-appointment.php#", "http://localhost/dams/doctor/appointment-bwdates.php", "http://localhost/dams/doctor/approved-appointment.php", "http://localhost/dams/doctor/appointment-bwdates.php#", "http://localhost/dams/doctor/approved-appointment.php#", "http://localhost/dams/doctor/cancelled-appointment.php", "http://localhost/dams/doctor/cancelled-appointment.php#", "http://localhost/dams/doctor/search.php#navbar-customizer", "http://localhost/dams/doctor/profile.php#navbar-customizer", "http://localhost/dams/doctor/search.php#menubar-customizer", "http://localhost/dams/doctor/profile.php#menubar-customizer", "http://localhost/dams/doctor/dashboard.php#navbar-customizer", "http://localhost/dams/doctor/dashboard.php#menubar-customizer", "http://localhost/dams/doctor/change-password.php#navbar-customizer", "http://localhost/dams/doctor/all-appointment.php#navbar-customizer", "http://localhost/dams/doctor/new-appointment.php#navbar-customizer", "http://localhost/dams/doctor/all-appointment.php#menubar-customizer", "http://localhost/dams/doctor/change-password.php#menubar-customizer", "http://localhost/dams/doctor/new-appointment.php#menubar-customizer", "http://localhost/dams/doctor/appointment-bwdates.php#navbar-customizer", "http://localhost/dams/doctor/approved-appointment.php#navbar-customizer", "http://localhost/dams/doctor/appointment-bwdates.php#menubar-customizer", "http://localhost/dams/doctor/approved-appointment.php#menubar-customizer", "http://localhost/dams/doctor/cancelled-appointment.php#navbar-customizer", "http://localhost/dams/doctor/cancelled-appointment.php#menubar-customizer", "http://localhost/dams/doctor/view-appointment-detail.php?editid=3&&aptid=485109480", "http://localhost/dams/doctor/view-appointment-detail.php?editid=4&&aptid=611388102", "http://localhost/dams/doctor/view-appointment-detail.php?editid=5&&aptid=607441873"]
```

None of these delete items or logout the user, so they can all be kept for the scanner.

Then, the script can be run again in its entirety.

Many parameters are available: ```pipenv run script --help```

# Parameters used for evaluation

```
pipenv run script  --config 'webapp_config.ini' --insert-empty --reset-fuzzing --reset-scanning --sensitive-rows --primary-keys --traversal column
```

# Links

https://www.cse.chalmers.se/research/group/security/spider-scents/#

https://www.usenix.org/conference/usenixsecurity24/presentation/olsson

# Ubuntu Environment

## dbfuzz on Ubuntu

### Install Python 3.10

```sudo apt install pipenv```

Install pyenv using its [automatic installer](https://github.com/pyenv/pyenv?tab=readme-ov-file#automatic-installer).

Install pyenv's [suggested build environment requirements](https://github.com/pyenv/pyenv/wiki#suggested-build-environment) for compiling Python on Ubuntu.

Python 3.10 and Python dependencies will be installed with ```pipenv install```

### Install Chrome

Install Chrome with its [deb package](https://www.google.com/chrome/?platform=linux).

[Download Chromedriver](https://googlechromelabs.github.io/chrome-for-testing/) and put the extracted binary on your path.

### Other dbfuzz system requirements

```sudo apt install mariadb-client```

```sudo apt install graphviz```

## Example web applications on Ubuntu

Install Docker using the [apt repository](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository).

## Tested versions

| Package/binary | --version | apt version |
|---|---|---|
| pipenv |  | 2023.12.1+ds-1 |
| pyenv | 2.4.7 |  |
| python | 3.10.14 |  |
| google-chrome-stable |  | 126.0.6478.182-1 |
| chromedriver | 126.0.6478.182 |  |
| mariadb-client |  | 1:10.11.8-0ubuntu0.24.04.1 |
| graphviz |  | 2.42.2-9ubuntu0.1 |
| docker-ce |  | 5:27.0.3-1\~ubuntu.22.04\~jammy |
| docker-ce-cli |  | 5:27.0.3-1\~ubuntu.22.04\~jammy |
| docker-compose-plugin |  | 2.28.1-1\~ubuntu.22.04\~jammy |

# Mac Environment

## Tested versions

| Package/binary | --version | brew version |
|---|---|---|
| pipenv | 2022.10.11 |  |
| python | 3.10.14 |  |
| Google Chrome | 126.0.6478.183 |  |
| chromedriver | 126.0.6478.182 |  |
| mariadb |  | stable 11.4.2 (bottled) |
| graphviz |  | stable 12.0.0 (bottled) |
| docker | 27.0.3, build 7d4bcd8 |  |


