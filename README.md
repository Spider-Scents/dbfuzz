# dbfuzz

dbfuzz is the prototype implementation of [Spider-Scents: Grey-box Database-aware Web Scanning for Stored XSS](https://www.cse.chalmers.se/research/group/security/spider-scents/#).

# Requirements

dbfuzz is written in Python, and requires Chrome and [Chromedriver](https://googlechromelabs.github.io/chrome-for-testing/), and mysql/mysqldump commands.
Python library requirements are available in the Pipfile of this repository.

Example web applications, located in the docker folder, are run with Docker and Docker Compose.

# To scan a web application

## Install Python 3.10

Python 3.10 is specified, but other adjacent versions likely work (untested).

## Install MySQL (or MariaDB)

This is only needed for the script to execute the ```mysql``` and ```mysqldump``` commands to restore and backup databases.

## Install Chrome and ChromeDriver: https://chromedriver.chromium.org

## Install Python packages: ```pipenv install```

## Launch your web application

Examples are included in the docker folder of this repository.

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