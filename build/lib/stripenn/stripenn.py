import argparse
import cooler
import multiprocessing
from joblib import Parallel, delayed
from stripenn import getStripe
import os
import shutil
import errno
import pandas as pd
import numpy as np
import warnings
import time
import sys
import logging

def argumentParser():
    parser = argparse.ArgumentParser(description='Stripenn')
    parser.add_argument("cool", help="Balanced cool file.")
    parser.add_argument('out', help="Path to output directory.")
    parser.add_argument("-k", '--chrom', help="Set of chromosomes. e.g., 'chr1,chr2,chr3', 'all' will generate stripes from all chromosomes", default='all')
    parser.add_argument("-c","--canny", help="Canny edge detection parameter.", default=2.5)
    parser.add_argument('-l','--minL', help="Minimum length of stripe.",default=10)
    parser.add_argument('-w','--maxW', help="Maximum width of stripe.",default=8)
    parser.add_argument('-m','--maxpixel', help="Percentiles of the contact frequency data to saturate the image. Separated by comma. Default = 0.95,0.96,0.97,0.98,0.99", default='0.95,0.96,0.97,0.98,0.99')
    num_cores = multiprocessing.cpu_count()
    parser.add_argument('-n','--numcores', help='The number of cores will be used.', default = num_cores)
    parser.add_argument('-p', '--pvalue', help='P-value cutoff for stripe.', default = 0.2)
    args = parser.parse_args()

    cool = args.cool
    out = args.out
    if out[-1] != '/':
        out += '/'
    chroms = args.chrom
    chroms = chroms.split(',')
    canny = float(args.canny)
    minH = int(args.minL)
    maxW = int(args.maxW)
    maxpixel = args.maxpixel
    maxpixel = maxpixel.split(',')
    maxpixel = list(map(float, maxpixel))
    core = int(args.numcores)
    pcut = float(args.pvalue)

    return(cool, out, chroms, canny, minH, maxW, maxpixel, core, pcut)

def makeOutDir(outdir, maxpixel):
    last = outdir[-1]
    if last != '/':
        outdir += '/'
    if os.path.exists(outdir):

        print('\n%s exists. Do you want to remove all files and save new results in this folder? [Y/n]' % (outdir))
        userinput = input()
        if userinput == 'Y' or userinput == 'y':
            print('All directories and files in %s will be deleted.' % (outdir))
            for filename in os.listdir(outdir):
                file_path = os.path.join(outdir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print('Failed to delete %s with the reason: %s' % (file_path, e))
        elif userinput == 'n' or userinput == 'N':
            print('Input another output directory. Exit.')
            quit()
        else:
            print('Type Y or n.\nExit.')
            quit()
    else:
        try:
            os.makedirs(outdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
    '''
    imagedir = os.path.join(outdir, 'images')
    os.makedirs(imagedir, mode=0o777, exist_ok=False)

    for mp in maxpixel:
        top = round(100*(1-mp),2)
        dirname = os.path.join(imagedir, 'top'+ str(top) + '%')
        os.makedirs(dirname, mode=0o777, exist_ok=False)
    '''
def main():
    t_start = time.time()
    cool, out, chroms, canny, minH, maxW, maxpixel, core, pcut = argumentParser()
    print('Result will be stored in %s' % (out))
    makeOutDir(out, maxpixel)
    Lib = cooler.Cooler(cool)
    all_chromnames = Lib.chromnames
    all_chromsizes = Lib.chromsizes
    chrom_remain_idx = np.where(all_chromsizes > 500000)[0]
    all_chromnames = [all_chromnames[i] for i in chrom_remain_idx]
    all_chromsizes = all_chromsizes[chrom_remain_idx]
    if len(all_chromnames) == 0:
        sys.exit("Exit: All chromosomes are shorter than 50kb.")
    warnflag = False
    if chroms[0] != 'all':
        idx = []
        for item in chroms:
            if item in all_chromnames:
                idx.append(all_chromnames.index(item))
            else:
                warnings.warn('\nThere is no chromosomes called '+str(item)+' in the provided .cool file or it is shorter than 50kb.')
                warnflag = True
        if warnflag:
            warnings.warn('\nThe possible chromosomes are: '+ ', '.join(all_chromnames))
        chromnames = chroms
        chromsizes = all_chromsizes[idx]


    unbalLib = Lib.matrix(balance=False)
    resol = Lib._info['bin-size']
    obj = getStripe.getStripe(unbalLib, resol, minH, maxW, canny, all_chromnames, chromnames, all_chromsizes, chromsizes,core)
    print('#######################################\nBackground distribution estimation ...\n#######################################\n')
    bgleft, bgright = getStripe.getStripe.nulldist(obj)
    print('#################################################\nFinding candidate stripes from each chromosome ...\n#################################################\n')
    result_table = pd.DataFrame(columns=['chr', 'pos1', 'pos2', 'chr2', 'pos3', 'pos4', 'length', 'width', 'total', 'Mean',
                                   'maxpixel', 'num', 'start', 'end', 'x', 'y', 'h', 'w', 'medpixel','pvalue'])
    for mp in maxpixel:
        result = obj.extract(mp, bgleft, bgright)
        result_table = result_table.append(result)

    result_table = getStripe.getStripe.RemoveRedundant(obj,df=result_table,by='pvalue')

    print('##########################\nStripiness calculation ...\n##########################\n')
    s = obj.scoringstripes(result_table)
    result_table = result_table.drop(columns=['total', 'num', 'start', 'end', 'x', 'y', 'h', 'w', 'medpixel'])
    result_table.insert(result_table.shape[1],'Stripiness',s,True)
    res_filter = result_table[result_table['pvalue'] < pcut]
    res_filter = res_filter.sort_values(by=['Stripiness'], ascending=False)

    res1 = out + 'result_unfiltered.txt'
    res2 = out + 'result_filtered.txt'

    result_table.to_csv(res1,sep="\t",header=True,index=False)
    res_filter.to_csv(res2,sep="\t",header=True,index=False)

    print('\n'+str(round((time.time()-t_start)/60,3))+'min taken.')
    print('Check the result stored in %s' % (out))
    return 0

if __name__ == "__main__":
    main()
