from urllib.parse import urlparse

from tqdm import tqdm

# TODO no need for helper? circular dependencies etc

# https://stackoverflow.com/questions/7160737/how-to-validate-a-url-in-python-malformed-or-not
def is_url(url: str) -> bool:
  """Check if a string is a URL"""

  try:
    result = urlparse(url)
    return all([result.scheme, result.netloc])
  except ValueError:
    return False

# controls logging and terminal output
WRITE_MESSAGES = True

def write_msg(msg: str) -> None:
  if WRITE_MESSAGES:
    tqdm.write(msg)