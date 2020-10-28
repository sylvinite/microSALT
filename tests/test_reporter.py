#!/usr/bin/env python

import datetime
import glob
import json
import logging
import os
import pathlib
import pdb
import pytest
import re
import sys

from distutils.sysconfig import get_python_lib
from unittest.mock import patch

from microSALT import preset_config, logger
from microSALT.utils.reporter import Reporter
from microSALT.utils.referencer import Referencer
from microSALT.store.db_manipulator import DB_Manipulator

def unpack_db_json(filename):
  testdata = os.path.abspath(os.path.join(pathlib.Path(__file__).parent.parent, 'tests/testdata/{}'.format(filename)))
  #Check if release install exists
  for entry in os.listdir(get_python_lib()):
    if 'microSALT-' in entry:
      testdata = os.path.abspath(os.path.join(os.path.expandvars('$CONDA_PREFIX'), 'testdata/{}'.format(filename)))
  with open(testdata) as json_file:
    data = json.load(json_file)
  return data

@pytest.fixture
def mock_db():
  db_file = re.search('sqlite:///(.+)', preset_config['database']['SQLALCHEMY_DATABASE_URI']).group(1)
  dbm = DB_Manipulator(config=preset_config,log=logger)
  dbm.create_tables()

  for antry in unpack_db_json('sampleinfo_projects.json'):
    dbm.add_rec(antry, 'Projects')
  for entry in unpack_db_json('sampleinfo_mlst.json'):
    dbm.add_rec(entry, 'Seq_types')
  for bentry in unpack_db_json('sampleinfo_resistance.json'):
    dbm.add_rec(bentry, 'Resistances')
  for centry in unpack_db_json('sampleinfo_expec.json'):
    dbm.add_rec(centry, 'Expacs')
  for dentry in unpack_db_json('sampleinfo_reports.json'):
    dbm.add_rec(dentry, 'Reports')
  return dbm

@pytest.fixture
def reporter():
  reporter_obj = Reporter(config=preset_config, log=logger, sampleinfo=unpack_db_json('sampleinfo_samples.json')[0], name="MIC1234A1", output="/tmp/MLST")
  return reporter_obj

def test_motif(mock_db, reporter):
  reporter.create_subfolders()
  reporter.gen_motif(motif="resistance")
  assert len( glob.glob("{}/AAA1234_resistance*".format(reporter.output))) > 0

  reporter.gen_motif(motif="expec")
  assert len( glob.glob("{}/AAA1234_expec*".format(reporter.output))) > 0

def test_deliveryreport(mock_db, reporter):
  reporter.create_subfolders()
  reporter.gen_delivery()
  assert len( glob.glob("{}/deliverables/999999_deliverables.yaml".format(preset_config['folders']['reports']))) > 0

def test_jsonreport(mock_db, reporter):
  reporter.create_subfolders()
  reporter.gen_json()
  assert len( glob.glob("{}/json/AAA1234.json".format(preset_config['folders']['reports']))) > 0

def test_gen_qc(mock_db, reporter):
  reporter.name = "name_that_do_not_exist"
  with pytest.raises(Exception):
    reporter.gen_qc()

def test_gen_typing(mock_db, reporter):
  reporter.name = "name_that_do_not_exist"
  with pytest.raises(Exception):
    reporter.gen_typing()

def test_gen_motif(caplog, reporter):
  caplog.clear()
  reporter.gen_motif(motif="unrecognized")
  assert "Invalid motif type" in caplog.text
  caplog.clear()
  reporter.output = "/path/that/do/not/exists/"
  reporter.gen_motif()
  assert "Gen_motif unable to produce" in caplog.text

def test_gen_json(caplog, reporter):
  caplog.clear()
  reporter.output = "/path/that/do/not/exists/"
  preset_config["folders"]["reports"] = "/path/that/do/not/exists/"
  reporter.config = preset_config
  reporter.gen_json()
  assert "Gen_json unable to produce" in caplog.text

def test_report(caplog, reporter):
  caplog.clear()
  reporter.type = "type_not_mentioned_in_list"
  with pytest.raises(Exception):
    reporter.report()
    assert "Report function recieved invalid format" in caplog.text

@patch('microSALT.utils.reporter.Reporter.start_web')
def test_restart_web(sw, reporter):
  reporter.restart_web()
