"""Scrapes output files for data and adds them to the database
   By: Isak Sylvin, @sylvinite"""

#!/usr/bin/env python

import glob
import os
import re
import string
import sys
import time

from microSALT.store.db_manipulator import DB_Manipulator
from microSALT.store.lims_fetcher import LIMS_Fetcher
from microSALT.utils.reporter import Reporter
from microSALT.utils.job_creator import Job_Creator

# TODO: Rewrite so samples use seperate objects
class Scraper():

  def __init__(self, infolder, config, log):
    self.config = config
    self.logger = log
    self.infolder = os.path.abspath(infolder)
    self.sampledir = ""
   
    last_folder = os.path.basename(os.path.normpath(self.infolder)) 
    self.name = last_folder.split('_')[0]
    #TODO: Replace date from dir with entry from analysis files/database
    self.date = "{} {}".format(re.sub('\.','-', last_folder.split('_')[1]), re.sub('\.',':', last_folder.split('_')[2]))
    self.db_pusher=DB_Manipulator(config, log)
    self.lims_fetcher=LIMS_Fetcher(config, log)
    self.job_fallback=Job_Creator("", config, log)
    self.lims_sample_info = {}
    self.gene2resistance = self.load_resistances()

  def scrape_project(self):
    """Scrapes a project folder for information"""
    if self.config['rerun']:
      self.db_pusher.purge_rec(self.name, 'project')
    if not self.db_pusher.exists('Projects', {'CG_ID_project':self.name}):
      self.logger.error("Re-filling project {}".format(self.name))
      self.job_fallback.create_project(self.name)

    #Scrape order matters a lot!
    for dir in os.listdir(self.infolder):
     if os.path.isdir("{}/{}".format(self.infolder, dir)): 
       self.sampledir = "{}/{}".format(self.infolder, dir)
       self.name = dir
       if not self.db_pusher.exists('Samples', {'CG_ID_sample':self.name}):
         self.logger.error("Re-filling sample {}".format(self.name))
         self.job_fallback.create_sample(self.name)
       self.scrape_all_loci()
       self.scrape_resistances()
       self.scrape_alignment()
       self.scrape_quast()

  def scrape_sample(self):
    """Scrapes a sample folder for information"""
    if self.config['rerun']:
      self.db_pusher.purge_rec(self.name, 'sample')

    self.lims_fetcher.load_lims_sample_info(self.name)
    if not self.db_pusher.exists('Projects', {'CG_ID_project':self.lims_fetcher.data['CG_ID_project']}):
      self.logger.error("Re-filling project {}".format(self.lims_fetcher.data['CG_ID_project']))
      self.job_fallback.create_project(self.lims_fetcher.data['CG_ID_project'])

    if not self.db_pusher.exists('Samples', {'CG_ID_sample':self.name}):
      self.logger.error("Re-filling sample {}".format(self.name))
      self.job_fallback.create_sample(self.name)

    #Scrape order matters a lot!
    self.sampledir = self.infolder
    self.scrape_all_loci()
    self.scrape_resistances()
    self.scrape_alignment()
    self.scrape_quast()

  def scrape_quast(self):
    """Scrapes a quast report for assembly information"""
    quast = dict()
    report = "{}/quast/report.tsv".format(self.sampledir)
    try:
      with open(report, 'r') as infile:
        for line in infile:
          lsplit = line.rstrip().split('\t')
          if lsplit[0] == '# contigs':
            quast['contigs'] = int(lsplit[1])
          elif lsplit[0] == 'Total length':
            quast['genome_length'] = int(lsplit[1])
          elif lsplit[0] == 'GC (%)':
            quast['gc_percentage'] = float(lsplit[1])
          elif lsplit[0] == 'N50':
            quast['n50'] = int(lsplit[1])

      self.db_pusher.upd_rec({'CG_ID_sample' : self.name}, 'Samples', quast)
      # Too spammy
      #self.logger.info("Project {} recieved quast stats: {}"\
      #               .format(self.name, quast))
    except Exception as e:
      self.logger.warning("Cannot generate quast statistics for {}".format(self.name))

  def get_locilength(self, analysis, reference, target):
    """ Find length of target within reference """
    alleles=dict()
    targetPre = ">{}".format(target)
    lastallele=""
    if analysis=="Resistances":
      filename="{}/{}.fsa".format(self.config["folders"]["resistances"], reference)
    elif analysis=="Seq_types":
      target = re.search('(.+)_(\w+)', target).group(1)
      filename="{}/{}/{}.tfa".format(self.config["folders"]["references"], reference, target)

    #Create dict with full name as key, associated nucleotides as value. 
    f = open(filename,"r")
    for row in f:
      if ">" in row:
        lastallele = row.strip()
        alleles[lastallele] = ""
      else:
        alleles[lastallele] = alleles[lastallele] + row.strip()
    f.close()
    try:
      return len(alleles[targetPre])
    except KeyError as e:
      self.logger.error("Target '{}' has been removed from current version of resFinder! Defaulting hit to length 1".format(targetPre))
      return 1

  def scrape_resistances(self):
    q_list = glob.glob("{}/resistance/*".format(self.sampledir))
    hypo = list()
    res_cols = self.db_pusher.get_columns('Resistances')
    for file in q_list:
      with open("{}".format(file), 'r') as sample:
        for line in sample:
          #Ignore commented fields
          if not line[0] == '#':
            elem_list = line.rstrip().split("\t")
            if not elem_list[1] == 'N/A':
              hypo.append(dict())
              hypo[-1]["CG_ID_sample"] = self.name
              hypo[-1]["identity"] = elem_list[4]
              hypo[-1]["evalue"] = elem_list[5]
              hypo[-1]["bitscore"] = elem_list[6]
              if int(elem_list[7]) < int(elem_list[8]):
                hypo[-1]["contig_start"] = int(elem_list[7])
                hypo[-1]["contig_end"] = int(elem_list[8])
              else:
                hypo[-1]["contig_start"] = int(elem_list[8])
                hypo[-1]["contig_end"] = int(elem_list[7])
              hypo[-1]["subject_length"] =  int(elem_list[11])

              # Split elem 3 in loci (name) and allele (number)
              partials = re.search('(.+)_(\d+){1,2}(?:_(\w+))*', elem_list[3])
              hypo[-1]["reference"] = partials.group(3)

              hypo[-1]["gene"] = partials.group(1)
              if hypo[-1]["gene"] in self.gene2resistance.keys():
                hypo[-1]["resistance"] = self.gene2resistance[hypo[-1]["gene"]]
              else:
                #Due to ass backwards naming conventions in recent resFinder, checking backwards
                trial = hypo[-1]["gene"]
                while len(trial) > 0: 
                  trial = trial[:-1]
                  if trial in self.gene2resistance.keys(): 
                    hypo[-1]['gene'] = trial
                    hypo[-1]["resistance"] = self.gene2resistance[trial]
                    break
                if len(trial) == 0:
                  raise Exception("Unable to associate resistance for {} of {} in {}".format(elem_list[3],hypo[-1]['CG_ID_sample'], os.path.basename(file)))
                self.logger.warn("Alternerative split for  hit {} of {}. Resolved to {}".format(elem_list[3], hypo[-1]['CG_ID_sample'], hypo[-1]['gene']))

              hypo[-1]["instance"] = os.path.basename(file[:-4])
              hypo[-1]["span"] = float(hypo[-1]["subject_length"])/self.get_locilength('Resistances', hypo[-1]["instance"], partials.group(0))

              # split elem 2 into contig node_NO, length, cov
              nodeinfo = elem_list[2].split('_')
              hypo[-1]["contig_name"] = "{}_{}".format(nodeinfo[0], nodeinfo[1])
              hypo[-1]["contig_length"] = int(nodeinfo[3])
              hypo[-1]["contig_coverage"] = nodeinfo[5]

    self.logger.info("{} candidate resistance hits found".format(len(hypo)))

    #Cleanup of overlapping hits
    ind = 0
    while ind < len(hypo)-1:
      targ = ind+1
      while targ < len(hypo):
        ignore = False
        if hypo[ind]["contig_name"] == hypo[targ]["contig_name"]:      
          #Overlapping or shared gene 
          debString = "{} ({}-{}) [id:{},span:{}] overlaps with (or shares name) {} ({}-{}) [id:{},span:{}].".format(hypo[ind]['gene'],hypo[ind]['contig_start'],hypo[ind]['contig_end'],hypo[ind]['identity'],hypo[ind]['span'],hypo[targ]['gene'],hypo[targ]['contig_start'],hypo[targ]['contig_end'],hypo[targ]['identity'],hypo[targ]['span'])
          if (hypo[ind]["contig_start"] >= hypo[targ]["contig_start"] and hypo[ind]["contig_start"] <= hypo[targ]["contig_end"]) or\
              (hypo[ind]["contig_end"] >= hypo[targ]["contig_start"] and hypo[ind]["contig_end"] <= hypo[targ]["contig_end"]) or \
              (hypo[ind]['gene'] == hypo[targ]['gene']):
            #Rightmost is worse
            if float(hypo[ind]["identity"])*(1-abs(1-hypo[ind]["span"])) >= float(hypo[targ]["identity"])*(1-abs(1-hypo[targ]["span"])):
              del hypo[targ]
              ignore = True
            #Leftmost is worse
            elif float(hypo[ind]["identity"])*(1-abs(1-hypo[ind]['span'])) < float(hypo[targ]["identity"])*(1-abs(1-hypo[targ]['span'])):
              del hypo[ind]
              targ = ind +1
              ignore = True
        if not ignore:
          targ += 1
        else:
          pass
          #self.logger.info("Debug: {}".format(debString))
      ind += 1

    self.logger.info("{} resistance hits were added after removing overlaps and duplicate hits".format( len(hypo)))
    for hit in hypo:
      self.db_pusher.add_rec(hit, 'Resistances')

  def load_resistances(self):
    """Loads common resistance names for genes"""
    conversions = dict()
    with open("{}/notes.txt".format(self.config["folders"]["resistances"])) as fh:
      for line in fh:
        if '#' not in line:
          line = line.split(':')
          cropped = re.sub(' resistance', '', line[1])
          conversions[line[0]] = cropped
          #Workaround for case issues
          conversions[line[0].lower()] = cropped
 
    ten = range(1, 10)
    for num in ten:
         conversions['qepA{}'.format(num)] = 'Quinolone'
         conversions['qnrA{}'.format(num)] = 'Quinolone'
         conversions['qnrD{}'.format(num)] = 'Quinolone'
         conversions['qnrE{}'.format(num)] = 'Quinolone'
         conversions['qnrS{}'.format(num)] = 'Quinolone'
         conversions['qnrVC{}'.format(num)] = 'Quinolone'
         conversions['blaACC-{}'.format(num)] = 'Beta-lactam'
         conversions["VanC{}XY".format(num)]="Glycopeptide"
         
    hun = range(1, 100)
    for num in hun:
         conversions['qnrB{}'.format(num)] = 'Quinolone'
         conversions['blaVIM-{}'.format(num)] = 'Beta-lactam'
         conversions['blaDHA-{}'.format(num)] = 'Beta-lactam'
         conversions['blaKPC-{}'.format(num)] = 'Beta-lactam'
         conversions['blaIMP-{}'.format(num)] = 'Beta-lactam'
         conversions['blaNDM-{}'.format(num)] = 'Beta-lactam'
         conversions['tet({})'.format(num)] = 'Tetracycline'
         conversions['tetA({})'.format(num)] = 'Tetracycline'
         conversions['tetB({})'.format(num)] = 'Tetracycline'
         conversions['erm({})'.format(num)]= 'Macrolide'
         conversions['mcr-{}.{}'.format(int(num)/10, num)] = 'Colistin'

    tho = range(1, 1000)
    for num in tho:
         conversions['blaOXA-{}'.format(num)] = 'Beta-lactam'
         conversions['blaCMY-{}'.format(num)] = 'Beta-lactam'
         conversions['blaSHV-{}'.format(num)] = 'Beta-lactam'
         conversions['blaTEM-{}'.format(num)] = 'Beta-lactam'
         conversions['blaCTX-M-{}'.format(num)] = 'Beta-lactam'
                                        
    letters = list(string.ascii_lowercase)
    for al in letters:
         conversions["mph({})".format(al.capitalize())]="Macrolide"
         conversions["VanH{}X".format(al.capitalize())]="Glycopeptide"
         conversions["blaOXA-114{}".format(al)]="Beta-lactam"
         conversions["blaACC-1{}".format(al)]="Beta-lactam"
        
    conversions["EstDL136"]="Phenicol"
    conversions["VanC2"]="Glycopeptide"
    conversions["VanEXY"]="Glycopeptide"
    conversions["VanG2XY"]="Glycopeptide"
    conversions["VanGXY"]="Glycopeptide"
    conversions["VanH"]="Glycopeptide"
    conversions["VanLXY"]="Glycopeptide"
    conversions["VanNXY"]="Glycopeptide"
    conversions["VanX"]="Glycopeptide"
    conversions["VanXY"]="Glycopeptide"
    conversions["aac(2')-IIa"]="Aminoglycoside"
    conversions["aac(3)-Ib-aac(6')-Ib'"]="Aminoglycoside"
    conversions["aac(6')-29a"]="Aminoglycoside"
    conversions["aac(6')-29b"]="Aminoglycoside"
    conversions["aac(6')-30-aac(6')-Ib'"]="Aminoglycoside"
    conversions["aac(6')-Iag"]="Aminoglycoside"
    conversions["aac(6')-Iaj"]="Aminoglycoside"
    conversions["aac(6')-Iak"]="Aminoglycoside"
    conversions["aac(6')-Ian"]="Aminoglycoside"
    conversions["aac(6')-Ib11"]="Aminoglycoside"
    conversions["aac(6')-Ib-11"]="Aminoglycoside"
    conversions["aac(6')-Ib-Hangzhou"]="Aminoglycoside"
    conversions["aac(6')-Ib-Suzhou"]="Aminoglycoside"
    conversions["aac(6')-Ib3"]="Aminoglycoside"
    conversions["aac(6')-Iid"]="Aminoglycoside"
    conversions["aac(6')-Iih"]="Aminoglycoside"
    conversions["aac(6')-Ip"]="Aminoglycoside"
    conversions["aac(6')-Ix"]="Aminoglycoside"
    conversions["aadA1b"]="Aminoglycoside"
    conversions["aadA2b"]="Aminoglycoside"
    conversions["aadA8b"]="Aminoglycoside"
    conversions["aadE-Cc"]="Aminoglycoside"
    conversions["ant(2'')-Ia"]="Aminoglycoside"
    conversions["ant(3'')-Ia"]="Aminoglycoside"
    conversions["ant(3'')-Ii-aac(6')-IIa"]="Aminoglycoside"
    conversions["ant(3'')-Ii-aac(6')-IIb"]="Aminoglycoside"
    conversions["ant(3'')-Ii-aac(6')-IIc"]="Aminoglycoside"
    conversions["ant(3'')-Ii-aac(6')-IId"]="Aminoglycoside"
    conversions["ant(9)-Ia"]="Aminoglycoside"
    conversions["aph(2'')-Ig"]="Aminoglycoside"
    conversions["aph(3'')-Ib"]="Aminoglycoside"
    conversions["aph(3')-IIIa"]="Aminoglycoside"
    conversions["aph(3')-IX"]="Aminoglycoside"
    conversions["aph(3')-VI"]="Aminoglycoside"
    conversions["aph(3')-VIj"]="Aminoglycoside"
    conversions["aph(6)-Id"]="Aminoglycoside"
    conversions["aph(7'')-Ia"]="Aminoglycoside"
    conversions["blaCMY-2b"]="Beta-lactam"
    conversions["blaCMY-8b"]="Beta-lactam"
    conversions["blaOXA535"]="Beta-lactam"
    conversions["blaSHV-1b-b"]="Beta-lactam"
    conversions["cfr(B)"]="Phenicol"
    conversions["cfr(C)"]="Phenicol"
    conversions["cmlB1"]="Phenicol"
    conversions["cmr"]="Macrolide"
    conversions["crpP"]="Quinolone"
    conversions["dfrA19"]="Trimethoprim"
    conversions["dldHA2X"]="Glycopeptide"
    conversions["ere(D)"]="Macrolide"
    conversions["erm(44)v"]="Macrolide"
    conversions["fexB"]="Phenicol"
    conversions["fmrO"]="Aminoglycoside"
    conversions["grmA"]="Aminoglycoside"
    conversions["grmB"]="Aminoglycoside"
    conversions["grmO"]="Aminoglycoside"
    conversions["kamB"]="Aminoglycoside"
    conversions["kgmB"]="Aminoglycoside"
    conversions["lnu(E)"]="Macrolide"
    conversions["lnu(G)"]="Macrolide"
    conversions["lnu(P)"]="Macrolide"
    conversions["mcr-8"]="Colistin"
    conversions["mdf(A)"]="Macrolide"
    conversions["mdt(A)"]="Macrolide"
    conversions["mecA1"]="Beta-lactam"
    conversions["mecA2"]="Beta-lactam"
    conversions["mecB"]="Beta-lactam"
    conversions["mecC2"]="Beta-lactam"
    conversions["mecD"]="Beta-lactam"
    conversions["mef(C)"]="Macrolide"
    conversions["mre(A)"]="Macrolide"
    conversions["otr(B)"]="Tetracycline"
    conversions["poxtA"]="Oxazolidinone"
    conversions["qnrC"]="Quinolone"
    conversions["rmtf"]="Aminoglycoside"
    conversions["sal(A)"]="Macrolide"
    conversions["sgm"]="Aminoglycoside"
    conversions["sul4"]="Sulphonamide"
    conversions["tcr3"]="Tetracycline"
    conversions["tet"]="Tetracycline"
    conversions["tet(O/32/O)"]="Tetracycline"
    conversions["tet(O/W)"]="Tetracycline"
    conversions["tet(O/W)-1"]="Tetracycline"
    conversions["tet(O/W)-2"]="Tetracycline"
    conversions["tet(O/W/32/O)"]="Tetracycline"
    conversions["tet(O/W/32/O/W/O)"]="Tetracycline"
    conversions["tet(O/W/O)-1"]="Tetracycline"
    conversions["tet(O/W/O)-2"]="Tetracycline"
    conversions["tet(O/W/O)-3"]="Tetracycline"
    conversions["tet(S/M)"]="Tetracycline"
    conversions["tet(W/32/O)"]="Tetracycline"
    conversions["tva(A)"]="Macrolide"
    conversions["vanXmurFvanKWI"]="Glycopeptide"
    conversions["vanXmurFvanWI"]="Glycopeptide"
    conversions["vat(H)"]="Macrolide"
    conversions["vga(A)V"]="Macrolide"
    conversions["vga(D)"]="Macrolide"
     
    return conversions

  def form_fingerprint(self, type):
    self.logger.info("Start cgMLST fingerprint generation. ETA 1-4 minutes per sample")
    if type == 'sample':
      self.lims_fetcher.load_lims_sample_info(self.name)
      self.sampledir = self.infolder
      self.scrape_cgmlst()
    elif type == 'project':
      for dir in os.listdir(self.infolder):
       if os.path.isdir("{}/{}".format(self.infolder, dir)):
         self.sampledir = "{}/{}".format(self.infolder, dir)
         self.name = dir
         start = time.time()
         self.scrape_cgmlst()
         self.logger.info("Time used for fingerprinting {}: {} seconds".format(self.name, int(time.time()-start)))
    else:
     self.logger.error("Invalid type programmed for cgMLST analysis")
     sys.exit(-1)

  def init_cgmlst(self):
    """Add downloaded gene list as default to database (if not already existing)"""
    organism = self.lims_fetcher.get_organism_refname(self.name)
    gene_list = "{}/{}.fna".format(self.config['folders']['gene_set'], organism)
    with open(gene_list, 'r') as gfile:
      for title in gfile:
        if title[0] == ">":
          title = title.replace('[','')
          title = title.replace(']','')
          title = title.replace('=',' ')
          #Title seperated
          title = title.split(' ')
          id = title[title.index('protein_id')+1]
          existing = self.db_pusher.query_rec('Profile_cgmlst', {'protein_id':id, 'organism':organism})
          if len(existing) < 1:
            self.db_pusher.add_rec({'protein_id':id, 'organism':organism, 'sequence':"Unassigned", 'allele':0}, 'Profile_cgmlst')

  def scrape_cgmlst(self):
    """Uploads cgmlst results to database and generates a fingerprint"""

    # self.init_cgmlst() <-- Unnecessary, only used for debugging. Even so needs revision, good idea though
    #Create sample specific node lookup table
    node_lookup = dict()
    ref_file = "{}/assembly/contigs.fasta".format(self.sampledir)
    with open (ref_file, 'r') as infile:
      for line in infile:
        if line[0] == ">":
          key = line[1:].rstrip()
          value = ""
        else:
          value += line.rstrip()
          node_lookup[key] = value

    #Associate each hit with it's sequence. BLAST displayed has some issues.
    allele_sequence = dict()
    res_file = "{}/cgmlst/loci_query_cgmlst.txt".format(self.sampledir)
    with open(res_file, 'r') as infile:
      for line in infile:
        if line[0] == "[":
          #Blast output seperated
          la = line.split('\t')
          title = la[0]
          title = title.replace('[','')
          title = title.replace(']','')
          title = title.replace('=',' ')
          #Title seperated
          title = title.split(' ')
          #Only unique pids for each sample
          id = title[title.index('protein_id')+1]
          if not id in allele_sequence:
            #la[-1] contains gaps
            #If competing PIDS, add one with lowest e-value
            if int(la[7]) < int(la[8]):
              #Indexes might be 1 away. Be careful
              allele_sequence[id] = node_lookup[la[2]][int(la[7]):int(la[8])]
            else:
              self.logger.error("Unhandled action. Index for {} come in reverse order".format(id))


    #Set all existing loci entries to N/A
    fp = dict()
    organism = self.lims_fetcher.get_organism_refname(self.name)

    #Check if found result exists in database
    for k,v in allele_sequence.items():
      span_threshold = 0.9
      push_dict = self.db_pusher.get_columns('Profile_cgmlst')
      top_index = self.db_pusher.top_index('Profile_cgmlst', {'protein_id':k, 'organism':organism}, 'allele')

      if top_index == -1:
        self.db_pusher.add_rec({'protein_id':k, 'organism':organism, 'sequence':v, 'allele':1}, 'Profile_cgmlst')
        fp[k] = 1
      else:
        exists = False
        for entry in self.db_pusher.query_rec('Profile_cgmlst', {'protein_id':k, 'organism':organism}):

          if entry.sequence in v and len(entry.sequence) > span_threshold*len(v):
            fp[k] = entry.allele
            exists = True
            self.db_pusher.upd_rec({'protein_id':k, 'organism':organism, 'allele':entry.allele}, 'Profile_cgmlst', {'sequence':v})
            break
          elif v in entry.sequence and len(v) > span_threshold*len(entry.sequence):
            fp[k] = entry.allele
            exists = True
            break
           
        if not exists:
          self.db_pusher.add_rec({'protein_id':k, 'organism':organism, 'sequence':v, 'allele':top_index+1}, 'Profile_cgmlst')
          fp[k] = top_index+1

    #Write fingerprint file
    fingerprint = "{}/cgmlst/fingerprint.txt".format(self.sampledir)
    fp_pointer = open(fingerprint,'w')
    for k, v in fp.items():
      fp_pointer.write("{}:{}\n".format(k,v))
    self.logger.info("Finished generating cgmlst results for {}".format(self.name)) 
  
  def scrape_all_loci(self):
    """Scrapes all BLAST output in a folder"""
    q_list = glob.glob("{}/blast/loci_query_*".format(self.sampledir))
    organism = self.lims_fetcher.get_organism_refname(self.name)
    self.db_pusher.upd_rec({'CG_ID_sample' : self.name}, 'Samples', {'organism': organism})

    for file in q_list:
      self.scrape_single_loci(file)
    #Requires all loci results to be initialized
    try:
      ST = self.db_pusher.alleles2st(self.name)
      self.db_pusher.upd_rec({'CG_ID_sample':self.name}, 'Samples', {'ST':ST})
      self.logger.info("Sample {} received ST {}".format(self.name, ST))
    except Exception as e:
      self.logger.error("{}".format(str(e)))

  def scrape_single_loci(self, infile):
    """Scrapes a single blast output file for MLST results"""

    seq_col = self.db_pusher.get_columns('Seq_types') 
    organism = self.lims_fetcher.get_organism_refname(self.name)
    if not os.path.exists(self.sampledir):
      self.logger.error("Invalid file path to infolder, {}".format(self.sampledir))
      sys.exit()
    try:
      with open("{}".format(infile), 'r') as insample:
        seq_col["CG_ID_sample"] = self.name

        for line in insample:
          #Ignore commented fields
          if not line[0] == '#':
            elem_list = line.rstrip().split("\t")
            if not elem_list[1] == 'N/A':
              seq_col["identity"] = elem_list[4]
              seq_col["evalue"] = elem_list[5]
              seq_col["bitscore"] = elem_list[6]
              if elem_list[7] < elem_list[8]:
                seq_col["contig_start"] = int(elem_list[7])
                seq_col["contig_end"] = int(elem_list[8])
              else:
                seq_col["contig_start"] = int(elem_list[8])
                seq_col["contig_end"] = int(elem_list[7])

              seq_col["subject_length"] = int(elem_list[11])
         
              # Split elem 3 in loci (name) and allele (number)
              partials = re.search('(.+)_(\d+){1,2}(?:_(\w+))*', elem_list[3]) 
              seq_col["loci"] = partials.group(1)
              seq_col["allele"] = int(partials.group(2))
              seq_col["span"] = float(seq_col["subject_length"])/self.get_locilength('Seq_types', organism, partials.group(0))

              # split elem 2 into contig node_NO, length, cov
              nodeinfo = elem_list[2].split('_')
              seq_col["contig_name"] = "{}_{}".format(nodeinfo[0], nodeinfo[1])
              seq_col["contig_length"] = int(nodeinfo[3])
              seq_col["contig_coverage"] = nodeinfo[5]
              self.db_pusher.add_rec(seq_col, 'Seq_types')
      # Too spammy
      #self.logger.info("Added allele {}={} of sample {} to table Seq_types".format(seq_col["loci"], seq_col["allele"], self.name))
    except Exception as e:
      self.logger.error("{}".format(str(e)))

  def scrape_alignment(self):
    """Scrapes a single alignment result"""
    ins_list = list()
    cov_dict = dict()
    align_dict = dict()
    align_dict["reference_genome"] = self.lims_fetcher.data['reference']

    q_list = glob.glob("{}/alignment/*.stats.*".format(self.sampledir))
    for file in q_list:
      with open(file, 'r') as fh:
       type = file.split('.')[-1]
       for line in fh.readlines():
         lsplit = line.rstrip().split('\t')
         if type == 'raw':
           tot_reads = int(lsplit[0])
         if type == 'ins':
           ins_list.append(int(lsplit[1]))
         elif type == 'cov':
           cov_dict[lsplit[1]] = int(lsplit[2])
         elif type == 'ref':
           if lsplit[0] != '*':
             ref_len = int(lsplit[1])
         elif type == 'map':
           dsplit = line.rstrip().split(' ')
           if len(dsplit)>= 5 and dsplit[4] == 'total':
             tot_map = int(dsplit[0])
           elif len(dsplit)>=4 and dsplit[3] == 'mapped':
             map_rate = int(dsplit[0])/float(tot_map)
         elif type == 'dup':
           dsplit = line.rstrip().split(' ')
           if dsplit[0] == 'DUPLICATE' and dsplit[1] == 'TOTAL':
             dup_bp = int(dsplit[2])
    #Post mangle
    #Fallbacks
    if len(ins_list) >= 1:
      median_ins = ins_list.index(max(ins_list))
    else:
      median_ins = 0
    sum, plus10, plus30, plus50, plus100, total = 0, 0, 0, 0, 0, 0
    for k, v in cov_dict.items():
      sum += int(k)*v
      total += v
      if int(k) > 10:
        plus10 += v
      if int(k) > 30:
        plus30 += v
      if int(k) > 50:
        plus50 += v
      if int(k) > 100:
        plus100 += v
    if total > 0:
      align_dict['coverage_10x'] = plus10/float(total)
      align_dict['coverage_30x'] = plus30/float(total)
      align_dict['coverage_50x'] = plus50/float(total)
      align_dict['coverage_100x'] = plus100/float(total)
    else:
      align_dict['coverage_10x'] = 0.0
      align_dict['coverage_30x'] = 0.0
      align_dict['coverage_50x'] = 0.0
      align_dict['coverage_100x'] = 0.0
 
    align_dict['mapped_rate'] = map_rate
    align_dict['insert_size'] = median_ins
    if ref_len > 0:
      align_dict['duplication_rate'] = dup_bp/float(ref_len)
      align_dict['average_coverage'] = sum/float(ref_len)
    else:
      align_dict['duplication_rate'] = 0.0
      align_dict['average_coverage'] = 0.0
    align_dict['total_reads'] = tot_reads
    self.db_pusher.upd_rec({'CG_ID_sample' : self.name}, 'Samples', align_dict)
