# dbfuzz

dbfuzz is the prototype implementation of [Spider-Scents: Grey-box Database-aware Web Scanning for Stored XSS](https://www.cse.chalmers.se/research/group/security/spider-scents/#).

# Requirements

dbfuzz is written in Python, and requires Chrome and [Chromedriver](https://googlechromelabs.github.io/chrome-for-testing/).
Python library requirements are available in the Pipfile of this repository.

# To run on a webapp

## Install Python 3.10

Python 3.10 is specified, but other adjacent versions likely work (untested).

## Install Chrome and ChromeDriver: https://chromedriver.chromium.org

## Install Python packages: ```pipenv install```

## Create a configuration for the webapp, with additional details such database and login credentials.

This can be based on config_sample.ini

## Then the scanner can be run with: ```pipenv run script --config 'webapp_config.ini'```

In the first run, the script will stop for you to remove dangerous URLs.

Remove dangerous URLs, such as those that delete items or log out the user, manually.

Then, the script can be run again in its entirety.

Many parameters are available: ```pipenv run script --help```

# Parameters used for evaluation

```
pipenv run script  --config 'webapp_config.ini' --insert-empty --reset-fuzzing --reset-scanning --sensitive-rows --primary-keys --traversal column
```

# Links

https://www.cse.chalmers.se/research/group/security/spider-scents/#

https://www.usenix.org/conference/usenixsecurity24/presentation/olsson