import os
import glob
import re

SNAKEMAKE_DIR= os.path.dirname(workflow.snakefile)

shell.executable("/bin/bash")
#shell.prefix("source %s/env_PSV.cfg; set -eo pipefail; " % SNAKEMAKE_DIR)
shell.prefix("source %s/env_PSV.cfg; set -eo pipefail" % SNAKEMAKE_DIR)
#shell.suffix("2> /dev/null")

blasr= '~mchaisso/projects/AssemblyByPhasing/scripts/abp/bin/blasr'
blasrDir= '~mchaisso/projects/blasr-repo/blasr'
scriptsDir= '/net/eichler/vol5/home/mchaisso/projects/AssemblyByPhasing/scripts/abp'
#base2="/net/eichler/vol21/projects/bac_assembly/nobackups/scripts"
base2="/net/eichler/vol2/home/mvollger/projects/abp"
utils="/net/eichler/vol2/home/mvollger/projects/utility"
PBS="/net/eichler/vol5/home/mchaisso/projects/PacBioSequencing/scripts" 
# Canu 1.5 seems to have muchhhh better performance over canu 1.6
CANU_DIR="/net/eichler/vol5/home/mchaisso/software/canu/Linux-amd64/bin"
#CANU_DIR="/net/eichler/vol21/projects/bac_assembly/nobackups/canu/Linux-amd64/bin"
#CANU_DIR="/net/eichler/vol2/home/mvollger/projects/builds/canu/Linux-amd64/bin"

groups= glob.glob("group.[0-9]*.vcf")
IDS= []
for group in groups:
    group= group.strip().split(".")
    assert group[0]=="group"
    IDS.append(group[1])


rule master:
    input: "PSV2_done"
    message: "Running PSV2"


# global wild card constraint on n whihc is the group idenitifier
wildcard_constraints:
    n="\d+"

#-----------------------------------------------------------------------------------------------------#
#
# make the group directories, and create a file that jsut acts as a tag for when the dir was created
#
rule makeGroupDirs:
    input:  expand('group.{ID}.vcf', ID=IDS)
    output: 
        group='group.{n}/',
        tag='group.{n}/group.{n}'
    shell:
        """
        rm -rf {output.group} # the assemblies will not re run properlly unless it starts fresh 
        mkdir -p {output.group} 
        echo "{output.tag}" >  {output.tag} 
        """
#-----------------------------------------------------------------------------------------------------#




#-----------------------------------------------------------------------------------------------------#
#
# this part partitions the reads based on the vcf files (PSVs)
#

# make a phased vcf for whatshap, just a format change
# also requires that pysam is installed, should be taken care of by loading the whatshap anaconda env 
rule phasedVCF:
    input: 'group.{n}/group.{n}',
        vcf= 'group.{n}.vcf'
    output: 'group.{n}/phased.{n}.vcf'
    shell:
        """
        source {base2}/env_whatshap.cfg 
        {base2}/fixVCF.py --out {output} --vcf {input.vcf}
        """

# whatshap requires unique bam entries, make those
# also requires that pysam is installed, should be taken care of by loading the whatshap anaconda env 
rule bamForWhatsHap:
    input: "reads.bam"
    output: 'reads.sample.bam'
    shell:
        """
        source {base2}/env_whatshap.cfg 
        {base2}/changeBamName.py
        """

# index reads.sample.bam
rule indexWhatshapReads:
    input:'reads.sample.bam'
    output: 'reads.sample.bam.bai',
    shell:
        """
        echo {output}
        samtools index {input}
        """ 

# run whats hap and get the partitioned sam files
rule whatsHap:
    input: 
        hapbam= 'reads.sample.bam',
        hapbai= 'reads.sample.bam.bai',
        hapvcf= 'group.{n}/phased.{n}.vcf'
    output: 
        hap= 'group.{n}/haplotagged.bam',
        hapH1= 'group.{n}/H1.WH.sam',
        hapH2= 'group.{n}/H2.WH.sam'
    threads: 1 # for some reason loading this env multiple times breaks it, so stop from parallel exe
                # this should no longer be nessisary as whatshap is installed in the new anaconda
    shell:
        """
        source {base2}/env_whatshap.cfg 
        #source activate whatshap  # this should no longer be nessisary as whatshap is installed in the new anaconda
        whatshap haplotag -o  {output.hap} --reference ref.fasta {input.hapvcf} {input.hapbam} 
        samtools view -h -o - {output.hap} | grep -E "^@|HP:i:1" >  {output.hapH1} 
        samtools view -h -o - {output.hap} | grep -E "^@|HP:i:2" >  {output.hapH2}
        """
#-----------------------------------------------------------------------------------------------------#



#-----------------------------------------------------------------------------------------------------#
#
# This is also a partitioning script but it was written by mark, and does not seem to work quite as well
# however I am still running it in order to comapre results
#
rule partitionReads:
    input: 
        vcf=  'group.{n}.vcf',
        pgroup= 'group.{n}/group.{n}',
        bam=  'reads.bam',
        # the following just makes sure whatshap is run first
        hapH2= 'group.{n}/H2.WH.sam'
    output:
        # these are switched from 1 and 2 because marks partition is the opposite of whatshap and I want
        # them to be the same H1 H2 convention from here on out
        group1='group.{n}/H2.Mark.sam',
        group2='group.{n}/H1.Mark.sam'
    shell:
    	"""
        #samtools view -h {input.bam} > temp.txt
        samtools view -h {input.bam} \
	    	| ~mchaisso/projects/pbgreedyphase/partitionByPhasedSNVs \
		    	--vcf {input.vcf} \
			    --ref ref.fasta \
			    --h1 {output.group1}  --h2 {output.group2} --sam /dev/stdin \
			    --unassigned /dev/null \
				    	--phaseStats group.{wildcards.n}/group.stats \
					    --block 4 \
					    --minGenotyped 2 \
					    --minDifference 3 \
                        || touch {output.group1} && touch {output.group2}
        """

# generate a fasta file from the partition
rule fastaFromPartition:
    input: 
        group1='group.{n}/H1.Mark.sam',
        group2='group.{n}/H2.Mark.sam'
    output:
        pfasta1='group.{n}/H1.Mark.fasta',
        pfasta2='group.{n}/H2.Mark.fasta'
    shell:
        '''
        grep -v "^@" {input.group1}  | awk '{{ print ">"$1; print $10;}}' > {output.pfasta1} 
        grep -v "^@" {input.group2}  | awk '{{ print ">"$1; print $10;}}' > {output.pfasta2}
        '''

        #'make -f {base2}/PartitionReads.mak VCF={input.vcf} OUTDIR=group.{wildcards.n}/group HAP=2'
#-----------------------------------------------------------------------------------------------------#



#-----------------------------------------------------------------------------------------------------#
#
# This part runs the assembly based on the partitions 
#

# get fasta files from the reads
# this should be changed if we decide to drop group.1.sam
rule readsFromSam:
    input: 
        H2= 'group.{n}/H2.{prefix}.sam',
        # the following just makes sure whatshap was run and that marks partition was run
        #hapH2=  'group.{n}/H2.WH.sam',
        #markH2= 'group.{n}/H2.Mark.sam' 
    output:
        pfasta= 'group.{n}/{prefix}.reads.fasta'
    shell:
        '''
        grep -v "^@" {input.H2} > group.{wildcards.n}/{wildcards.prefix}.temp.txt
        if [ -s group.{wildcards.n}/{wildcards.prefix}.temp.txt ]
        then
            cat group.{wildcards.n}/{wildcards.prefix}.temp.txt | {PBS}/local_assembly/StreamSamToFasta.py | \
                ~mchaisso/projects/PacBioSequencing/scripts/falcon/FormatFasta.py --fakename  > {output.pfasta}
        else
            >&2 echo " no real fasta file for assembly"
            touch {output.pfasta}
        fi
        rm -f group.{wildcards.n}/{wildcards.prefix}.temp.txt 
        '''

# run the assembly
rule runAssembly:
    input: 'group.{n}/{prefix}.reads.fasta'
    output: 'group.{n}/{prefix}.assembly/asm.contigs.fasta'
    threads: 16
    shell:
        '''
        if [ -s {input} ]; then
            module load java/8u25 && {CANU_DIR}/canu -pacbio-raw {input} genomeSize=60000 \
                -d group.{wildcards.n}/{wildcards.prefix}.assembly \
		        -p asm useGrid=false  gnuplotTested=true  corMhapSensitivity=high corMinCoverage=1 \
		        maxThreads={threads} cnsThreads={threads} ovlThreads={threads} \
		        mhapThreads={threads} contigFilter="2 1000 1.0 1.0 2" \
                || ( >&2 echo " no real assembly" && \
                mkdir -p group.{wildcards.n}/{wildcards.prefix}.assembly && \
                > {output} )

        else
            >&2 echo " no real assembly"
            mkdir -p group.{wildcards.n}/{wildcards.prefix}.assembly
            > {output}
        fi
        '''

# this is currently not being run, uncooment the input line from assemblyReport, to start running it, and add additional code 
# to handle it
rule runFalcon:
    input:
        canu = 'group.{n}/{prefix}.assembly/asm.contigs.fasta',
        reads = 'group.{n}/{prefix}.reads.fasta',
    output:
       'group.{n}/{prefix}.assembly/falcon.readme'
    threads: 16
    shell:
        """
        # if the assembly is empty lets try out falcon, and the reads file is not empty 
        if [ ! -s  {input.canu} ] && [ -s {input.reads} ]; then
            
            make a falcon dir
            mkdir -p group.{wildcards.n}/{wildcards.prefix}.assembly/falcon

            # put the reads in an fofn for falcon
            echo $(readlink -f {input.reads}) > group.{wildcards.n}/{wildcards.prefix}.assembly/falcon/input.fofn
            
            # move into the assembly directory 
            pushd group.{wildcards.n}/{wildcards.prefix}.assembly/falcon/

            # setup falcon
            PBS=~mchaisso/projects/PacBioSequencing/scripts
            BLASR=~mchaisso/projects/blasr-repo/blasr
            MMAP=~mchaisso/software/minimap
            MASM=~mchaisso/software/miniasm
            QUIVER=~mchaisso/software/quiver
            PBG=~mchaisso/projects/pbgreedyphase
            
            # run falcon
            source ~mchaisso/scripts/setup_falcon.sh && fc_run.py ~mchaisso/projects/PacBioSequencing/scripts/local_assembly/falcon/fc_run.low_cov.cfg
           
            # move the assembly into the spot of the other assembly 
            cp 2-asm-falcon/p_ctg.fa ../asm.contigs.fasta

            popd 

            echo "Falcon Ran" > {output} 

        else
            # not running falcon
            echo "Canu worked so falcon did not run" > {output}
        fi
        
        """

# check if the assembly is not size 0
rule assemblyReport:
    input:  
        oasm= 'group.{n}/{prefix}.assembly/asm.contigs.fasta',
        preads='group.{n}/{prefix}.reads.fasta',
        #falcon='group.{n}/{prefix}.assembly/falcon.readme'
    output: 
        asm=  'group.{n}/{prefix}.assembly.fasta',
        report='group.{n}/{prefix}.report.txt'
    shell:
        """
        if [ -s {input.oasm} ]
        then
            cp {input.oasm} {output.asm}
	        echo "Number of reads " > {output.report}
	        grep -c ">" {input.preads} >> {output.report}
	        echo "Assembly number of contigs" >> {output.report}
	        module load numpy/latest; ~mchaisso/software/mcsrc/UTILS/pcl {input.preads} \
                    | ~mchaisso/scripts/stats.py >> {output.report}
	        rm -rf templocal
        else
            touch {output.asm}
            touch {output.report}
        fi
        """ 


# if samtobas fails it is becasue we started with no qual information and it kills it
rule bamFromAssembly:
    input:
        asm= 'group.{n}/{prefix}.assembly.fasta',
        H2= 'group.{n}/H2.{prefix}.sam', # samtobas is not robust enough to work if I start without qual info so using fasta
        preads='group.{n}/{prefix}.reads.fasta',
    output: 
        asmbam= 'group.{n}/{prefix}.assembly.bam',
        asmbas= 'group.{n}/{prefix}.reads.bas.h5'
    threads: 16
    shell:
        """
        if [ ! -s {input.asm} ] 
	    then
            # create empty files, this will allow other rules to conitnue 
		    > {output.asmbam}
            > {output.asmbas}
        else 
            ~mchaisso/projects/blasr-repo/blasr/pbihdfutils/bin/samtobas {input.H2} {output.asmbas} -defaultToP6
	        ~mchaisso/projects/blasr-repo/blasr/alignment/bin/blasr {output.asmbas} {input.asm} \
                -clipping subread -sam -bestn 1 -out /dev/stdout  -nproc {threads} \
                | samtools view -bS - | samtools sort -T tmp -o {output.asmbam}
	        
            samtools index {output.asmbam}
        fi
        """

rule quiverFromBam:
    input:
        asmbam= 'group.{n}/{prefix}.assembly.bam',
        asm= 'group.{n}/{prefix}.assembly.fasta'
    output:
        quiver= 'group.{n}/{prefix}.assembly.consensus.fasta',
    threads: 16
    shell:
        '''
        # check 
        if [ ! -s {input.asm} ] 
	    then
            # create empty files, this will allow other rules to conitnue 
		    > {output.quiver}
        else
            samtools faidx {input.asm}
	        source ~mchaisso/software/quiver/setup_quiver.sh; ~mchaisso/software/quiver/bin/quiver \
		        --noEvidenceConsensusCall nocall --minCoverage 10 -j {threads} \
		        -r {input.asm} -o {output.quiver} {input.asmbam}
            
            # add the head of the non quivered file
            header=$(head -n 1 {input.asm})
            header2=">group.{wildcards.n}_quiver "$(echo $header | sed -e 's/>//')
            sed -i "1s/.*/$header2/" {output.quiver} 
        fi
        '''
#-----------------------------------------------------------------------------------------------------#




#-----------------------------------------------------------------------------------------------------#
#
# map back to duplications.fasta to determine the region wiht the highest %ID and 
# the average %Id acrosss all the regions in the human reference
# (in the furture I may add soemthing that does this for non quivered files)
#
if(os.path.exists("duplications.fasta")):
    rule newName:
        input:
            "duplications.fasta"
        output:
            dup="duplications.fixed.fasta",
        shell:
            '''
             awk 'BEGIN{{count=1}}{{if($0~/^>/){{print ">copy"count,$0;count++}}else{{print}}}}' \
                     < duplications.fasta | sed -e 's/ >chr/\tchr/g' > {output.dup}
            '''


    rule bestMappings:
        input:
            dup="duplications.fixed.fasta",
            quiver= 'group.{n}/{prefix}.assembly.consensus.fasta',
            preads= 'group.{n}/H2.{prefix}.sam',
        output:
            best= 'group.{n}/{prefix}.best.m4',
            average= 'group.{n}/{prefix}.average.m4',
            best5= 'group.{n}/{prefix}.best.m5',
            average5= 'group.{n}/{prefix}.average.m5',
        shell:
            """
            if [ ! -s {input.quiver} ] 
	        then
                # create empty files, this will allow other rules to conitnue 
		        > {output.best}
                > {output.average}
                > {output.best5}
                > {output.average5}
            else
                {blasr} {input.dup} {input.quiver} -bestn 1 -header -m 4 > {output.average}
                {blasr} {input.quiver} {input.dup} -bestn 1 -header -m 4 > {output.best}
                {blasr} {input.dup} {input.quiver} -bestn 1 -m 5 > {output.average5}
                {blasr} {input.quiver} {input.dup} -bestn 1 -m 5 > {output.best5}
            fi
            """ 

    rule mapBackPartition:
        input:
            dup="duplications.fixed.fasta",
            quiver= 'group.{n}/{prefix}.assembly.consensus.fasta',
            #preads= 'group.{n}/{prefix}.reads.fasta',
            preads= 'group.{n}/H2.{prefix}.sam',
        output:
            psam= 'group.{n}/{prefix}.{n}.sam',
            pbam= 'group.{n}/{prefix}.{n}.bam',
        shell:
            """
            if [ ! -s {input.preads} ] 
	        then
                # create empty files, this will allow other rules to conitnue 
                > {output.psam}
                > {output.pbam}
            else
                {blasr} {input.preads} {input.dup} -bestn 1 -sam > {output.psam}
                samtools view -b {output.psam} \
                        | samtools sort -o {output.pbam}
                #samtools view -S -b -o temp.bam {output.psam}
                #samtools sort -o {output.pbam} temp.bam
                samtools index {output.pbam}
                #rm temp.bam
            fi
            """
    
    rule truePSVs:
        input:
            dup="duplications.fixed.fasta",
            ref='ref.fasta',
            cuts='mi.gml.cuts',
            vcf='assembly.consensus.nucfreq.vcf'
        output:
            truth="truth/README.txt",
            refsam="refVSdup.sam",
            refsnv="refVSdup.snv",
            truthmatrix="truth.matrix"
        shell:
            """
            mkdir -p truth
            echo "exists" > {output.truth}
             
            blasr {input.dup} {input.ref} -sam -bestn 1 > {output.refsam} 
            
            /net/eichler/vol5/home/mchaisso/projects/PacBioSequencing/scripts/PrintGaps.py \
                    {input.ref} {output.refsam} --snv {output.refsnv} > refVSdup.SV
           
            ~mchaisso/projects/AssemblyByPhasing/scripts/utils/CompareRefSNVWithPSV.py \
                    --ref {output.refsnv} --psv {input.cuts} --vcf {input.vcf} \
                    --refFasta {input.ref} --writevcf truth/true > truth.matrix
            
            """

else:
    rule noMapping:
        input:
            quiver= 'group.{n}/{prefix}.assembly.consensus.fasta',
            reads= 'group.{n}/H2.{prefix}.sam',
        output:
            best= 'group.{n}/{prefix}.best.m4',
            average= 'group.{n}/{prefix}.average.m4',
            best5= 'group.{n}/{prefix}.best.m5',
            average5= 'group.{n}/{prefix}.average.m5',
        shell:
            """
            > {output.average}
            > {output.best}
            > {output.best5}
            > {output.average5}
            """

    rule noMappingBest:
        input:
            quiver= 'group.{n}/{prefix}.assembly.consensus.fasta',
            reads= 'group.{n}/H2.{prefix}.sam',
        output:
            sam= 'group.{n}/{prefix}.best.sam',
            bam= 'group.{n}/{prefix}.best.bam',
            psam= 'group.{n}/{prefix}.{n}.sam',
            pbam= 'group.{n}/{prefix}.{n}.bam',
        shell:
            """
            > {output.bam}
            > {output.sam}
            > {output.pbam}
            > {output.psam}
            """
    
    rule noTruePSVs:
        input:
            ref='ref.fasta',
            cuts='mi.gml.cuts',
            vcf='assembly.consensus.nucfreq.vcf'
        output:
            truth="truth/README.txt",
        shell:
            """
            mkdir -p truth
            echo "does not exist" > {output.truth}
            """



#-----------------------------------------------------------------------------------------------------#




#-----------------------------------------------------------------------------------------------------#
#
# checks to see if the assembly exists and if not removes the empty file if it does not and all other 
# empty files
# creats a group output file
# then creats a empty file singinaling we are done
# removeing empty files is actually a bad idea with snakemake becuase it will try to re run canu next time, when we know it will jsut fail
#
rule removeEmptyAsm:
    input:
        # commenting the following line should remove Marks partitioning script from the required assembly
        #eMark=expand( 'group.{ID}/Mark.best.m4', ID=IDS),
        eWH=expand( 'group.{ID}/WH.best.m4',   ID=IDS),
        e5WH=expand( 'group.{ID}/WH.best.m5',   ID=IDS),
        esam=expand( 'group.{ID}/WH.{ID}.sam',   ID=IDS),
        ebam=expand( 'group.{ID}/WH.{ID}.bam',   ID=IDS),
    output: 'removeEmpty'
    shell:
        """
        # removes any empty assemblies we may have created along the way 
        #find group.*/ -maxdepth 1 -size  0  | xargs -n 1 rm -f 
        touch {output}
        """

#cat group.*/Mark.assembly.consensus.fasta > {output.asmMark} || > {output.asmMark}
rule combineAsm:
    input:
        remove='removeEmpty', 
    output: 
        asmWH='WH.assemblies.fasta',
        #asmMark='Mark.assemblies.fasta'
    shell:
        """
        rm {input.remove}
        cat   group.*/WH.assembly.consensus.fasta > {output.asmWH}   || > {output.asmWH}
        """

#
rule map_asms_to_ref:
    input:
        asmWH="WH.assemblies.fasta",
        ref="ref.fasta"
    output:
        WHm5="WH.m5",
    shell:
        """
        blasr -m 5 -bestn 1 -out {output.WHm5} {input.asmWH} {input.ref}
        """


rule map_asms_to_duplicaitons:
    input:
        asmWH="WH.assemblies.fasta",
        ref="duplications.fasta"
    output:
        WHm5="WH_dup.m5",
    shell:
        """
        blasr -m 5 -bestn 1 -out {output.WHm5} {input.asmWH} {input.ref}
        """

# old asm.bed file
'''
rule bedForGRcH38:
    input:
        WHm5="WH_dup.m5",
    output:
        asmbed="asm.bed"
    run:
        import re
        rtn = ""
        m5 = open(input["WHm5"])
        for line in m5:
            token = line.strip().split(" ")
            key = token[5]
            temp = re.split(":|-", key)
            chr = temp[0]
            start = int(temp[1])
            end = int(temp[2])
            contig = token[0]
            mstart = int(token[7])
            mend = int(token[8])
            diff = mend - mstart 
            perID = float(token[11])/(float(token[11]) + float(token[12]))
            realStart = start + mstart
            realEnd = realStart + diff
            rtn += "{}\t{}\t{}\t{}\t{}\t{}\n".format(chr, realStart, realEnd, perID, contig, diff) 
        
        f = open(output["asmbed"], "w+")
        f.write(rtn)
'''


rule plot_seqs_on_dup:
    input:
        depth="dup_depth.tsv",
        WHm5="WH_dup.m5"
    output:
        "seqsOnDup.png",
    shell:
        """
        {utils}/plotDepth.py {input.depth} {output} --m5 {input.WHm5}
        """

rule plot_seqs_on_cov:
    input:
        depth="depth.tsv",
        WHm5="WH.m5"
    output:
        "seqs.png",
    shell:
        """
        {utils}/plotDepth.py {input.depth} {output} --m5 {input.WHm5}
        """

#
#
#
rule bedForTrack:
    input:
        bed="ref.fasta.bed",
        whdup="WH_dup.m5",
    output:
        asmbed="asm.bed",
    shell:
        """
        bedForABP.py
        """



#
# runs a summary script that just consilidates some data, which is later sued in plotting
#
rule summary:
    input:
        combine='WH.assemblies.fasta',
        truth="truth/README.txt",
    output:
        summary="summary.txt",
    shell:
        """
        {base2}/summary.py
        """



# pdf='mi.cuts.gml.pdf',
rule final:
    input:
        combine='WH.assemblies.fasta',
        summary="summary.txt",
        truth="truth/README.txt",
        seqPNG="seqs.png",
        dupPND="seqsOnDup.png",
        asmbed="asm.bed",
    output: 'PSV2_done'
    shell:
        """
        touch {output}
        """
#-----------------------------------------------------------------------------------------------------#



    
    
