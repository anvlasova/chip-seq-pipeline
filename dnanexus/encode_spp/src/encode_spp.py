#!/usr/bin/env python
# encode_spp 0.0.1
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

import os, subprocess, shlex, time
from multiprocessing import Pool, cpu_count
from subprocess import Popen, PIPE #debug only this should only need to be imported into run_pipe
import dxpy

def run_pipe(steps, outfile=None):
    #break this out into a recursive function
    #TODO:  capture stderr
    from subprocess import Popen, PIPE
    p = None
    p_next = None
    first_step_n = 1
    last_step_n = len(steps)
    for n,step in enumerate(steps, start=first_step_n):
        print "step %d: %s" %(n,step)
        if n == first_step_n:
            if n == last_step_n and outfile: #one-step pipeline with outfile
                with open(outfile, 'w') as fh:
                    print "one step shlex: %s to file: %s" %(shlex.split(step), outfile)
                    p = Popen(shlex.split(step), stdout=fh)
                break
            print "first step shlex to stdout: %s" %(shlex.split(step))
            p = Popen(shlex.split(step), stdout=PIPE)
            #need to close p.stdout here?
        elif n == last_step_n and outfile: #only treat the last step specially if you're sending stdout to a file
            with open(outfile, 'w') as fh:
                print "last step shlex: %s to file: %s" %(shlex.split(step), outfile)
                p_last = Popen(shlex.split(step), stdin=p.stdout, stdout=fh)
                p.stdout.close()
                p = p_last
        else: #handles intermediate steps and, in the case of a pipe to stdout, the last step
            print "intermediate step %d shlex to stdout: %s" %(n,shlex.split(step))
            p_next = Popen(shlex.split(step), stdin=p.stdout, stdout=PIPE)
            p.stdout.close()
            p = p_next
    out,err = p.communicate()
    return out,err

@dxpy.entry_point('main')
def main(experiment, control, xcor_scores_input, npeaks):

    # The following line(s) initialize your data object inputs on the platform
    # into dxpy.DXDataObject instances that you can start using immediately.

    experiment_file = dxpy.DXFile(experiment)
    control_file = dxpy.DXFile(control)
    xcor_scores_input_file = dxpy.DXFile(xcor_scores_input)

    # The following line(s) download your file inputs to the local file system
    # using variable names for the filenames.

    experiment_filename = experiment_file.name
    dxpy.download_dxfile(experiment_file.get_id(), experiment_filename)
    control_filename = control_file.name
    dxpy.download_dxfile(control_file.get_id(), control_filename)
    xcor_scores_input_filename = xcor_scores_input_file.name
    dxpy.download_dxfile(xcor_scores_input_file.get_id(), xcor_scores_input_filename)

    output_filename_prefix = experiment_filename.rstrip('.gz').rstrip('.tagAlign')
    peaks_filename = output_filename_prefix + '.regionPeak.gz'
    xcor_plot_filename = output_filename_prefix + '.pdf'
    xcor_scores_filename = output_filename_prefix + '.ccscores'

    print subprocess.check_output('ls -l', shell=True)

    fraglen_column = 3 # third column in the cross-correlation scores input file
    with open(xcor_scores_input_filename, 'r') as f:
        line = f.readline()
        fragment_length = int(line.split('\t')[fraglen_column-1])
        print "Read fragment length: %d" %(fragment_length)

    #run_spp_command = subprocess.check_output('which run_spp.R', shell=True)
    spp_tarball = '/phantompeakqualtools/spp_1.10.1.tar.gz'
    run_spp = '/phantompeakqualtools/run_spp.R'
    #install spp
    print subprocess.check_output(shlex.split('R CMD INSTALL %s' %(spp_tarball)))
    out, err = run_pipe([
        "Rscript %s -p=%d -c=%s -i=%s -npeak=%d -speak=%d -savr=%s -savp=%s -rf -out=%s" \
            %(run_spp, cpu_count(), experiment_filename, control_filename, npeaks, fragment_length, peaks_filename, xcor_plot_filename, xcor_scores_filename)])

    #open("peaks",'a').close()
    #open("xcor_plot").close()
    #open("xcor_scores").close()
    peaks = dxpy.upload_local_file(peaks_filename)
    xcor_plot = dxpy.upload_local_file(xcor_plot_filename)
    xcor_scores = dxpy.upload_local_file(xcor_scores_filename)

    # The following line fills in some basic dummy output and assumes
    # that you have created variables to represent your output with
    # the same name as your output fields.

    output = {}
    output["peaks"] = dxpy.dxlink(peaks)
    output["xcor_plot"] = dxpy.dxlink(xcor_plot)
    output["xcor_scores"] = dxpy.dxlink(xcor_scores)

    return output

dxpy.run()
