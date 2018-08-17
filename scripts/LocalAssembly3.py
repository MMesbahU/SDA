#!/usr/bin/env python
import glob
import subprocess
import os
import sys
import re
import itertools 
import os
import pandas as pd
import numpy as np
pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 20000000)
#pd.set_option('display.float_format', lambda x: '%.3f' % x)
from Bio import SeqIO
if sys.version_info[0] < 3: 
    from StringIO import StringIO
else:
    from io import StringIO
import pysam

class LocalAssembly:	
	def __init__(self, mydir, assembler, psvGraphLoc=None, psvURLPATH=None):
		self.mydir = os.path.abspath(mydir.strip()) + "/"
		self.asm = assembler
		self.determineGroups()
		# this means there were zero groups generated by CC
		if(len(self.ids) == 0):
			return 
		self.findAsm()
		self.fillInFailed()
		self.addStatus()
		self.addPSVs()
		self.addReads()
		self.addCommon()
		self.truthMatrix()
		self.addSeqs()
		#print(self.all.to_string(index=False))
		self.toFile()
	
	def addReads(self):
		self.numReads = []
		for idx in self.ids:
			sam = "{}group.{}/H2.WH.bam".format(self.mydir, idx)
			reads = 0
			if(os.path.exists(sam)):
				f = pysam.AlignmentFile(sam)
				for rec in f.fetch(until_eof=True):
					reads += 1
				#f = open(sam)
				#for line in f:
				#	line = line.strip()
				#	if(line[0] not in ["@", "\n", "\t", " "] ):
				#		reads += 1
			self.numReads.append(reads)

		temp = pd.DataFrame({"numReads":self.numReads, "CC_ID":self.ids})
		self.all = pd.merge( self.all, temp, how='left', on ="CC_ID")
		
		sam = self.mydir + "reads.fasta"
		reads = 0
		if(os.path.exists(sam)):
			f = open(sam)
			for line in f:
				line = line.strip()
				if(line[0] == ">" ):
					reads += 1
		self.totalReads = reads
		self.all["totalReads"] = reads 

	def addSeqs(self):
		fasta = self.mydir + self.asm + ".assemblies.fasta"
		Seqs = SeqIO.to_dict(SeqIO.parse(fasta, "fasta"))
		toadd = []
		for fastaid in self.all["query_name"]:
			if(fastaid in Seqs):
				toadd.append(Seqs[fastaid].seq)
			else:
				toadd.append("NA")
		self.all["seq"] = toadd 


	def toFile(self):
		#fname = self.mydir + self.collapse + ".table.tsv"
		fname = self.mydir + self.asm +  ".abp.table.tsv"
		subset = []
		for col in list(self.all):
			if(type(col) != np.int64 ):
				subset.append(col)
		self.subset = self.all[subset]
		self.subset.to_csv(fname, sep = "\t", index = False)

	def addPSVs(self):
		self.numPSVs = []
		psv = self.mydir + "CC/mi.gml.cuts"
		self.numPSVs = []
		if(os.path.exists(psv)):
			f = open(psv)
			for idx, line in enumerate(f):
				line = line.strip()
				line = line.split("\t")
				self.numPSVs.append( len(line) )
		
		temp = pd.DataFrame({"numPSVs":self.numPSVs, "CC_ID":self.ids})
		self.all = pd.merge( self.all, temp, how='left', on ="CC_ID")
		self.all["totalPSVs"] = sum(self.numPSVs)

	def addCommon(self):
		self.collapse = os.path.basename(self.mydir[:-1])
		ref = list(SeqIO.parse(self.mydir + "ref.fasta", "fasta"))[0]
		self.collapseLen = len( ref.seq )
		self.refRegions = []
		lens = []
		dups = self.mydir + "ref.fasta.bed"
		if(os.path.exists(dups)):
			f = open(dups)
			for dup in f:
				dup = dup.strip()
				match = re.match("(.*)\t(\d+)\t(\d+)", dup)
				chr = match.group(1)
				start = int( match.group(2))
				end = int(match.group(3))
				lens.append(end-start)
				self.refRegions.append("{}:{}-{}".format(chr, start, end))
		self.aveRefLength = np.mean(lens)
	

		self.all["copiesInRef"] = len(self.refRegions) 
		self.all["numOfCCgroups"] = len(self.ids)
		self.all["numOfAssemblies"] = self.numPR + self.numR
		self.all["numF"] = self.numF
		self.all["numMA"] = self.numMA
		self.all["numPR"] = self.numPR
		self.all["numR"] = self.numR
		self.all["collapse"] = self.collapse
		self.all["collapseLen"] = self.collapseLen 
		self.all["aveRefLength"] = self.aveRefLength
		self.all["refRegions"] = ";".join(self.refRegions)

	def truthMatrix(self):
		tm = self.mydir + "truth/truth.matrix"
		if( os.path.exists(tm) ):
			tm = pd.read_table(tm, header=None, skiprows=1, sep = '\s+')
			tm.rename(columns={0: 'CC_ID'}, inplace=True)
			self.all = pd.merge( self.all, tm, how='left', on ="CC_ID")

	def addStatus(self):
		status = []
		self.numMA = 0
		self.numR = 0
		self.numPR = 0
		self.numF = 0
		for x in self.ids:
			if( sum(self.all["CC_ID"]==x) > 1 ):
				status.append("Multiple Assemblies")
				self.numMA += 1
			elif(x in self.failed ): #or self.asms[self.asms.CC_ID == x]["bestPerID"].iloc[0] < 0.95 ):
				status.append("Failed")
				self.numF += 1
			elif( self.asms[self.asms.CC_ID == x]["perID_by_matches"].iloc[0] < 99.8 ):
				status.append("Diverged")
				self.numPR += 1
			else:
				status.append("Resolved")
				self.numR += 1
		add = pd.DataFrame({"CC_ID":self.ids, "Status":status})
		self.all = pd.merge( self.all, add, how='left', on ="CC_ID")

	def fillInFailed(self):
		self.failed = list( set(self.ids) - set(self.asms.CC_ID)   )
		self.fails = None
		names = list(self.asms)
		fails = []
		for fail_ID in self.failed:
			dic = {}
			for name in names:
				dic[name] = "NA"
			dic["CC_ID"] = fail_ID
			rtn = pd.Series(dic)
			fails.append(rtn)
		if(len(self.failed) > 0):
			self.fails = pd.concat(fails, axis = 1,ignore_index=True).T 
			self.all=pd.concat([self.fails, self.asms], ignore_index=True)
		else:
			self.all = self.asms
		self.all.sort_values("CC_ID", inplace=True)
		self.all.reset_index(drop=True, inplace=True)

	def determineGroups(self):
		vcfs = glob.glob(self.mydir + "group.*.vcf")
		self.ids = []
		self.groups = {}
		for vcf in vcfs:
			match = re.match(".*group\.(\d*)\.vcf$", vcf)
			ID = int(match.group(1))
			self.ids.append(ID)
			self.groups[ID] = "{}group.{}/".format(self.mydir,ID)
		self.ids = sorted(self.ids)

	def nameToCCid(self, df):
		records = list(SeqIO.parse(self.mydir + self.asm + ".assemblies.fasta", "fasta"))
		query_name = []
		length = []
		CC_ID = []
		curCCid = -1 
		for rec in records:
			match = re.match("group\.(\d*)_.*$", rec.id)
			if(match is not None):
				curCCid = int(match.group(1))
			CC_ID.append(curCCid)
			query_name.append(rec.id)
			length.append(len(rec.seq))
		names = pd.DataFrame( {"query_name":query_name, "CC_ID":CC_ID, "Length":length})
		merged = pd.merge(df, names, how='outer', on ="query_name" )
		merged.sort_values("CC_ID", inplace=True)
		merged.reset_index(drop=True, inplace=True)
		return(merged)
	
	def parseBestMatch(self):
		self.asms["bestChr"] = ""
		self.asms["bestMatch"] = ""
		self.asms["bestStart"] = -1
		self.asms["bestEnd"] = -1
		for idx, row in self.asms.iterrows():
			chrm="noMatch"
			start = 0
			end = 0
			if(type(row["reference_name"]) is str ):
				match = re.match( "(.*):(\d*)-(\d*)", row["reference_name"] )
				chrm = match.group(1) 
				start = int(match.group(2)) + int( row["reference_start"])
				end = int(match.group(2)) + int( row["reference_end"])
			
			match = "{}:{}-{}".format(chrm, start, end)
			
			self.asms.set_value(idx,"bestChr", chrm)
			self.asms.set_value(idx,"bestStart", start)
			self.asms.set_value(idx,"bestEnd", end)
			self.asms.set_value(idx,"bestMatch", match)

	def findAsm(self):
		asms = []
		df = pd.read_csv(self.mydir + "asms/{}.dup.tbl".format(self.asm), sep = "\t")
		self.asms = self.nameToCCid(df)
		self.parseBestMatch()





#LocalAssembly("/net/eichler/vol21/projects/bac_assembly/nobackups/genomeWide/Mitchell_CHM1/LocalAssemblies/000000F.6046000.6065699")
#test="/net/eichler/vol21/projects/bac_assembly/nobackups/genomeWide/Mitchell_CHM1/LocalAssemblies/{}"
#collapse = "000000F.6046000.6065699"
#test = test.format(collapse)
#LocalAssembly(test)


