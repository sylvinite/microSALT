import collections
import logging
import json
import os
import sys

from flask import Flask

__version__ = '2.8.23'

app = Flask(__name__, template_folder='server/templates')
app.config.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
app.config.setdefault('SQLALCHEMY_BINDS', None)
app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)

#Keep track of microSALT installation
wd=os.path.dirname(os.path.realpath(__file__))

# Load configuration
config = ''
default = os.path.join(os.environ['HOME'], '.microSALT/config.json')

if 'MICROSALT_CONFIG' in os.environ:
  try:
    envvar = os.environ['MICROSALT_CONFIG']
    with open(envvar, 'r') as conf:
      config = json.load(conf)
  except Exception as e:
    print("Config error: {}".format(str(e)))
    pass
elif os.path.exists(default):
  try:
    with open(os.path.abspath(default), 'r') as conf:
      config = json.load(conf)
  except Exception as e:
    print("Config error: {}".format(str(e))) 
    pass
# Load flask instance
if config != '':
  try:
    app.config.update(config['database'])
  except Exception as e:
    print("Config error: {}".format(str(e)))
    pass

#Initialize logger
logger = logging.getLogger('main_logger')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler(os.path.expanduser(config['folders']['log_file']))
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
logger.addHandler(ch)

#Create paths mentioned in config
for entry in config.keys():
  if entry != '_comment':
    if isinstance(config[entry], str) and '/' in config[entry] and entry not in ['database', 'genologics']:
      unmade_fldr = os.path.dirname(config[entry])
      if not os.path.isdir(unmade_fldr):
        os.makedirs(unmade_fldr)
        logger.info("Created path {}".format(unmade_fldr))

    #level two
    elif isinstance(config[entry], collections.Mapping):
      for thing in config[entry].keys():
        if isinstance(config[entry][thing], str) and '/' in config[entry][thing] and entry not in ['database', 'genologics']:
          unmade_fldr = os.path.dirname(config[entry][thing])
          if not os.path.isdir(unmade_fldr):
            os.makedirs(unmade_fldr)
            logger.info("Created path {}".format(unmade_fldr))
