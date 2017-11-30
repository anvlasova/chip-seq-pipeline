#!/usr/bin/env python
# filter_qc 0.0.1
# Generated by dx-app-wizard.
#
# Basic execution pattern: Your app will run on a single machine from
# beginning to end.
#
# See https://wiki.dnanexus.com/Developer-Portal for documentation and
# tutorials on how to modify this file.
#
# DNAnexus Python Bindings (dxpy) documentation:
#   http://autodoc.dnanexus.com/bindings/python/current/

import os
import subprocess
import shlex
import re
import common
import dxpy
import logging
from multiprocessing import cpu_count
from pprint import pprint, pformat

logger = logging.getLogger(__name__)
logger.addHandler(dxpy.DXLogHandler())
logger.propagate = False
logger.setLevel(logging.INFO)


def dup_parse(fname):
    with open(fname, 'r') as dup_file:
        if not dup_file:
            return None

        lines = iter(dup_file.read().splitlines())

        for line in lines:
            if line.startswith('## METRICS CLASS'):
                headers = lines.next().rstrip('\n').lower()
                metrics = lines.next().rstrip('\n')
                break

        headers = headers.split('\t')
        metrics = metrics.split('\t')
        headers.pop(0)
        metrics.pop(0)

        dup_qc = dict(zip(headers, metrics))
    return dup_qc


def pbc_parse(fname):
    with open(fname, 'r') as pbc_file:
        if not pbc_file:
            return None

        lines = pbc_file.read().splitlines()
        line = lines[0].rstrip('\n')
        # PBC File output:
        #   TotalReadPairs <tab>
        #   DistinctReadPairs <tab>
        #   OneReadPair <tab>
        #   TwoReadPairs <tab>
        #   NRF=Distinct/Total <tab>
        #   PBC1=OnePair/Distinct <tab>
        #   PBC2=OnePair/TwoPair

        headers = ['TotalReadPairs',
                   'DistinctReadPairs',
                   'OneReadPair',
                   'TwoReadPairs',
                   'NRF',
                   'PBC1',
                   'PBC2']
        metrics = line.split('\t')

        pbc_qc = dict(zip(headers, metrics))
    return pbc_qc


def flagstat_parse(fname):
    with open(fname, 'r') as flagstat_file:
        if not flagstat_file:
            return None
        flagstat_lines = flagstat_file.read().splitlines()

    qc_dict = {
        # values are regular expressions,
        # will be replaced with scores [hiq, lowq]
        'in_total': 'in total',
        'duplicates': 'duplicates',
        'mapped': 'mapped',
        'paired_in_sequencing': 'paired in sequencing',
        'read1': 'read1',
        'read2': 'read2',
        'properly_paired': 'properly paired',
        'with_self_mate_mapped': 'with itself and mate mapped',
        'singletons': 'singletons',
        # i.e. at the end of the line
        'mate_mapped_different_chr': 'with mate mapped to a different chr$',
        # RE so must escape
        'mate_mapped_different_chr_hiQ':
            'with mate mapped to a different chr \(mapQ>=5\)'
    }

    for (qc_key, qc_pattern) in qc_dict.items():
        qc_metrics = next(re.split(qc_pattern, line)
                          for line in flagstat_lines
                          if re.search(qc_pattern, line))
        (hiq, lowq) = qc_metrics[0].split(' + ')
        qc_dict[qc_key] = [int(hiq.rstrip()), int(lowq.rstrip())]

    return qc_dict


@dxpy.entry_point('main')
def main(input_bam, paired_end, samtools_params, scrub, debug):

    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    raw_bam_file = dxpy.DXFile(input_bam)
    raw_bam_filename = raw_bam_file.name
    raw_bam_basename = raw_bam_file.name.rstrip('.bam')
    raw_bam_file_mapstats_filename = raw_bam_basename + '.flagstat.qc'
    dxpy.download_dxfile(raw_bam_file.get_id(), raw_bam_filename)
    subprocess.check_call('ls -l', shell=True)

    # Generate initial mapping statistics
    with open(raw_bam_file_mapstats_filename, 'w') as fh:
        flagstat_command = "samtools flagstat %s" % (raw_bam_filename)
        logger.info(flagstat_command)
        subprocess.check_call(shlex.split(flagstat_command), stdout=fh)

    filt_bam_prefix = raw_bam_basename + ".filt.srt"
    filt_bam_filename = filt_bam_prefix + ".bam"
    if paired_end:
        # =============================
        # Remove  unmapped, mate unmapped
        # not primary alignment, reads failing platform
        # Remove low MAPQ reads
        # Only keep properly paired reads
        # ==================
        tmp_filt_bam_prefix = "tmp.%s" % (filt_bam_prefix)  # was tmp.prefix.nmsrt
        tmp_filt_bam_filename = tmp_filt_bam_prefix + ".bam"
        out, err = common.run_pipe([
            # filter: -F 1804 FlAG bits to exclude; -f 2 FLAG bits to reqire;
            # -q 30 exclude MAPQ < 30; -u uncompressed output
            # exclude FLAG 1804: unmapped, next segment unmapped, secondary
            # alignments, not passing platform q, PCR or optical duplicates
            # require FLAG 2: properly aligned
            "samtools view -F 1804 -f 2 %s -u %s" % (samtools_params, raw_bam_filename),
            # sort:  -n sort by name; - take input from stdin;
            # out to specified filename
            # Will produce name sorted BAM
            "samtools sort -@ %d -n -o %s" % (cpu_count(), tmp_filt_bam_filename)])
        if err:
            logger.error("samtools error: %s" % (err))
        # Remove orphan reads (pair was removed)
        # and read pairs mapping to different chromosomes
        # Obtain position sorted BAM
        subprocess.check_call('ls -l', shell=True)
        out, err = common.run_pipe([
            # fill in mate coordinates, ISIZE and mate-related flags
            # fixmate requires name-sorted alignment; -r removes secondary and
            # unmapped (redundant here because already done above?)
            # - send output to stdout
            "samtools fixmate -r %s -" % (tmp_filt_bam_filename),
            # repeat filtering after mate repair
            "samtools view -F 1804 -f 2 -u -",
            # produce the coordinate-sorted BAM
            "samtools sort -@ %d -o %s" % (cpu_count(), filt_bam_filename)])
        subprocess.check_call('ls -l', shell=True)
    else:  # single-end data
        # =============================
        # Remove unmapped, mate unmapped
        # not primary alignment, reads failing platform
        # Remove low MAPQ reads
        # ==================
        with open(filt_bam_filename, 'w') as fh:
            samtools_filter_command = (
                "samtools view -F 1804 %s -b %s"
                % (samtools_params, raw_bam_filename)
                )
            logger.info(samtools_filter_command)
            subprocess.check_call(
                shlex.split(samtools_filter_command),
                stdout=fh)

    # ========================
    # Mark duplicates
    # ======================
    tmp_filt_bam_filename = raw_bam_basename + ".dupmark.bam"
    dup_file_qc_filename = raw_bam_basename + ".dup.qc"
    picard_string = ' '.join([
        "java -Xmx4G -jar /picard/MarkDuplicates.jar",
        "INPUT=%s" % (filt_bam_filename),
        "OUTPUT=%s" % (tmp_filt_bam_filename),
        "METRICS_FILE=%s" % (dup_file_qc_filename),
        "VALIDATION_STRINGENCY=LENIENT",
        "ASSUME_SORTED=true",
        "REMOVE_DUPLICATES=false"
        ])
    logger.info(picard_string)
    subprocess.check_output(shlex.split(picard_string))
    os.rename(tmp_filt_bam_filename, filt_bam_filename)

    if paired_end:
        final_bam_prefix = raw_bam_basename + ".filt.srt.nodup"
    else:
        final_bam_prefix = raw_bam_basename + ".filt.nodup.srt"
    final_bam_filename = final_bam_prefix + ".bam"  # To be stored
    final_bam_index_filename = final_bam_filename + ".bai"  # To be stored
    # QC file
    final_bam_file_mapstats_filename = final_bam_prefix + ".flagstat.qc"

    # ============================
    # Remove duplicates
    # Index final position sorted BAM
    # ============================
    if paired_end:
        samtools_dedupe_command = \
            "samtools view -F 1804 -f2 -b %s" % (filt_bam_filename)
    else:
        samtools_dedupe_command = \
            "samtools view -F 1804 -b %s" % (filt_bam_filename)
    with open(final_bam_filename, 'w') as fh:
        logger.info(samtools_dedupe_command)
        subprocess.check_call(
            shlex.split(samtools_dedupe_command),
            stdout=fh)
    # Index final bam file
    samtools_index_command = \
        "samtools index %s %s" % (final_bam_filename, final_bam_index_filename)
    logger.info(samtools_index_command)
    subprocess.check_call(shlex.split(samtools_index_command))

    # Generate mapping statistics
    with open(final_bam_file_mapstats_filename, 'w') as fh:
        flagstat_command = "samtools flagstat %s" % (final_bam_filename)
        logger.info(flagstat_command)
        subprocess.check_call(shlex.split(flagstat_command), stdout=fh)

    # =============================
    # Compute library complexity
    # =============================
    # Sort by name
    # convert to bedPE and obtain fragment coordinates
    # sort by position and strand
    # Obtain unique count statistics
    pbc_file_qc_filename = final_bam_prefix + ".pbc.qc"
    # PBC File output
    # TotalReadPairs [tab]
    # DistinctReadPairs [tab]
    # OneReadPair [tab]
    # TwoReadPairs [tab]
    # NRF=Distinct/Total [tab]
    # PBC1=OnePair/Distinct [tab]
    # PBC2=OnePair/TwoPair
    if paired_end:
        steps = [
            "samtools sort -@ %d -n %s" % (cpu_count(), filt_bam_filename),
            "bamToBed -bedpe -i stdin",
            r"""awk 'BEGIN{OFS="\t"}{print $1,$2,$4,$6,$9,$10}'"""]
    else:
        steps = [
            "bamToBed -i %s" % (filt_bam_filename),
            r"""awk 'BEGIN{OFS="\t"}{print $1,$2,$3,$6}'"""]
    steps.extend([
        "grep -v 'chrM'",
        "sort",
        "uniq -c",
        r"""awk 'BEGIN{mt=0;m0=0;m1=0;m2=0} ($1==1){m1=m1+1} ($1==2){m2=m2+1} {m0=m0+1} {mt=mt+$1} END{printf "%d\t%d\t%d\t%d\t%f\t%f\t%f\n",mt,m0,m1,m2,m0/mt,m1/m0,m1/m2}'"""
        ])
    out, err = common.run_pipe(steps, pbc_file_qc_filename)
    if err:
        logger.error("PBC file error: %s" % (err))

    # ===================
    # Generate bed-like files from filtered mappings
    # ===================
    # Create tagAlign file
    # ===================
    if paired_end:
        end_infix = 'PE2SE'
    else:
        end_infix = 'SE'
    final_TA_filename = final_bam_prefix + '.' + end_infix + '.tagAlign.gz'
    out, err = common.run_pipe([
        "bamToBed -i %s" % (final_bam_filename),
        r"""awk 'BEGIN{OFS="\t"}{$4="N";$5="1000";print $0}'""",
        "gzip -cn"],
        outfile=final_TA_filename)

    if paired_end:
        # ================
        # Create BEDPE file
        # ================
        final_BEDPE_filename = final_bam_prefix + ".bedpe.gz"
        # need namesorted bam to make BEDPE
        final_nmsrt_bam_filename = final_bam_prefix + ".nmsrt.bam"
        samtools_sort_command = \
            "samtools sort -n -@ %d -o %s %s" % (cpu_count(), final_nmsrt_bam_filename, final_bam_filename)
        logger.info(samtools_sort_command)
        subprocess.check_call(shlex.split(samtools_sort_command))
        out, err = common.run_pipe([
            "bamToBed -bedpe -mate1 -i %s" % (final_nmsrt_bam_filename),
            "gzip -cn"],
            outfile=final_BEDPE_filename)

    output = {}
    logger.info("Uploading results files to the project")
    filtered_bam = dxpy.upload_local_file(final_bam_filename)
    filtered_bam_index = dxpy.upload_local_file(final_bam_index_filename)
    tagAlign_file = dxpy.upload_local_file(final_TA_filename)
    output.update({
        "filtered_bam": dxpy.dxlink(filtered_bam),
        "filtered_bam_index": dxpy.dxlink(filtered_bam_index),
        "tagAlign_file": dxpy.dxlink(tagAlign_file)
    })
    if paired_end:
        BEDPE_file = dxpy.upload_local_file(final_BEDPE_filename)
        output.update({
            "BEDPE_file": dxpy.dxlink(BEDPE_file)
        })

    # If the scrub parameter is true, pass the bams to the scrub applet.
    if scrub:
        scrub_applet = dxpy.find_one_data_object(
            classname='applet',
            name='scrub',
            project=dxpy.PROJECT_CONTEXT_ID,
            zero_ok=False,
            more_ok=False,
            return_handler=True)
        scrub_subjob = \
            scrub_applet.run(
                {"input_bams": [input_bam, dxpy.dxlink(filtered_bam)]},
                name='Scrub bams')
        scrubbed_unfiltered_bam = scrub_subjob.get_output_ref("scrubbed_bams", index=0)
        scrubbed_filtered_bam = scrub_subjob.get_output_ref("scrubbed_bams", index=1)
        # Add the optional scrubbed outputs.
        output.update({
            "scrubbed_unfiltered_bam": dxpy.dxlink(scrubbed_unfiltered_bam),
            "scrubbed_filtered_bam": dxpy.dxlink(scrubbed_filtered_bam)
        })

    # Upload or calculate the remaining outputs.
    filtered_mapstats = \
        dxpy.upload_local_file(final_bam_file_mapstats_filename)
    dup_file = dxpy.upload_local_file(dup_file_qc_filename)
    pbc_file = dxpy.upload_local_file(pbc_file_qc_filename)

    logger.info("Calcualting QC metrics")
    dup_qc = dup_parse(dup_file_qc_filename)
    pbc_qc = pbc_parse(pbc_file_qc_filename)
    initial_mapstats_qc = flagstat_parse(raw_bam_file_mapstats_filename)
    final_mapstats_qc = flagstat_parse(final_bam_file_mapstats_filename)
    if paired_end:
        useable_fragments = final_mapstats_qc.get('in_total')[0]/2
    else:
        useable_fragments = final_mapstats_qc.get('in_total')[0]
    logger.info("initial_mapstats_qc:\n%s" % (pformat(initial_mapstats_qc)))
    logger.info("final_mapstats_qc:\n%s" % (pformat(final_mapstats_qc)))
    logger.info("dup_qc:\n%s" % (pformat(dup_qc)))
    logger.info("pbc_qc:\n%s" % (pformat(pbc_qc)))

    # Return links to the output files and values.
    output.update({
        "filtered_mapstats": dxpy.dxlink(filtered_mapstats),
        "dup_file_qc": dxpy.dxlink(dup_file),
        "pbc_file_qc": dxpy.dxlink(pbc_file),
        "paired_end": paired_end,
        "n_reads_input": str(initial_mapstats_qc.get('in_total')[0]),
        "picard_read_pairs_examined": str(dup_qc.get('read_pairs_examined')),
        "picard_unpaired_reads_examined": str(dup_qc.get('unpaired_reads_examined')),
        "picard_read_pair_duplicates": str(dup_qc.get('read_pair_duplicates')),
        "picard_unpaired_read_duplicates": str(dup_qc.get('unpaired_read_duplicates')),
        "useable_fragments": str(useable_fragments),
        "NRF": str(pbc_qc.get('NRF')),
        "PBC1": str(pbc_qc.get('PBC1')),
        "PBC2": str(pbc_qc.get('PBC2')),
        "duplicate_fraction": str(dup_qc.get('percent_duplication'))
    })
    logger.info("Exiting with output:\n%s" % (pformat(output)))
    return output


dxpy.run()
