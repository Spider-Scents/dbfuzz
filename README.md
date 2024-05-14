To run on a webapp:
Install Chrome and ChromeDriver: https://chromedriver.chromium.org
Install packages: pipenv install
Create a configuration for the webapp, with additional details such database and login credentials.
This can be based on config_sample.ini
Then the scanner can be run with: pipenv run script --config 'webapp_config.ini'
In the first run, the script will stop for you to remove dangerous URLs.
Remove dangerous URLs, such as those that delete items, manually.
Then, the script can be run again in its entirety.

Many parameters are available: pipenv run script --help
Parameters used for evaluation are:
pipenv run script  --config 'webapp_config.ini' --insert-empty --reset-fuzzing --reset-scanning --sensitive-rows --primary-keys --traversal column