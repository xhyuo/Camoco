#!/usr/bin/env python3

import argparse
import sys
import os
import copy

import numpy as np
import scipy as sp
import scipy.stats

from collections import OrderedDict

import camoco as co
import pandas as pd
import matplotlib.pylab as plt

def density(args):
    # Handle the different output schemes
    if args.out is None:
        args.out = '{}_{}_{}_{}_{}'.format(
            cob.name,
            ont.name,
            args.candidate_window_size,
            args.candidate_flank_limit,
            ':'.join(args.terms)
        )
    args.out = os.path.splitext(args.out)[0] + '.density.tsv'
    if os.path.dirname(args.out) != '':
        os.makedirs(os.path.dirname(args.out),exist_ok=True)
    if os.path.exists(args.out) and args.force != True:
        print(
            "Output for {} exists! Skipping!".format(
                args.out
            ),file=sys.stderr
        )
        return
    # Build base camoco objects
    cob = co.COB(args.cob)
    ont = co.GWAS(args.gwas)
    # Generate a terms iterable
    if 'all' in args.terms:
        terms = ont.iter_terms()
    else:
        terms = [ont[term] for term in args.terms]
    
    all_results = list()

    for term in terms:
        print("Boostrapping Density for {} of {} in {}".format(
            term.id,
            ont.name,
            cob.name
        ),file=sys.stderr)
   
        if 'effective' in args.snp2gene:
            # Map to effective
            loci = term.effective_loci(
                window_size=args.candidate_window_size
            )
        elif 'strongest' in args.snp2gene:
            loci = term.strongest_loci(
                window_size=args.candidate_window_size,
                attr=args.strongest_attr,
                lowest=args.strongest_higher
            )
    
        if args.gene_specific == True:
            # generate emirical and bootstrap values 
            gene_density = cob.trans_locus_density(
                loci,
                flank_limit=args.candidate_flank_limit,
                by_gene = True,
                bootstrap = False
            )
            # Generate bootstraps for trans locus density
            bootstraps = pd.concat([
                cob.trans_locus_density(
                    loci,
                    flank_limit=args.candidate_flank_limit,
                    iter_name = x,
                    by_gene = True,
                    bootstrap = True
                ) for x in range(args.num_bootstraps)
            ])
            bs_mean = bootstraps.groupby('iter').score.apply(np.mean).mean()
            bs_std  = bootstraps.groupby('iter').score.apply(np.std).mean()
            # Calculate z scores for density
            gene_density['zscore'] = (gene_density.score-bs_mean)/bs_std
            gene_density['fdr'] = np.nan
            bootstraps['zscore'] = (bootstraps.score-bs_mean)/bs_std
            max_zscore = int(gene_density.zscore.max()) + 1
            for zscore in np.arange(0, max_zscore,0.25):
                num_random = bootstraps\
                        .groupby('iter')\
                        .apply(lambda df: sum(df.zscore >= zscore))\
                        .mean()
                num_real = sum(gene_density.zscore >= zscore)
                # Calculate FDR
                if num_real != 0 and num_random != 0:
                    fdr = num_random / num_real
                elif num_real != 0 and num_random == 0:
                    fdr = 0
                else:
                    fdr = 1
                gene_density.loc[gene_density.zscore >= zscore,'fdr'] = fdr
                gene_density.loc[gene_density.zscore >= zscore,'num_real'] = num_real
                gene_density.loc[gene_density.zscore >= zscore,'num_random'] = num_random
                gene_density.loc[gene_density.zscore >= zscore,'bs_mean'] = bs_mean
                gene_density.loc[gene_density.zscore >= zscore,'bs_std'] = bs_std
                gene_density.sort_values(by='fdr',ascending=True,inplace=True)
                # This gets collated into all_results below
                results = gene_density
        else:
            results = OrderedDict()
            # Grab gene candidates
            candidates = cob.refgen.candidate_genes(
                loci, flank_limit=args.candidate_flank_limit
            )
            emp_density = cob.trans_locus_density(
                loci,
                flank_limit=args.candidate_flank_limit,
                bootstrap=False
            )
            # Effective Loci Bootstraps
            bootstraps = np.array([
                cob.trans_locus_density(
                    loci,
                    by_gene=False,
                    flank_limit=args.candidate_flank_limit,
                    bootstrap=True
                ) for x in range(args.num_bootstraps)
            ])
            # Calculate the p-value 
            effective_pval = sum([bs >= emp_density for bs in bootstraps])
            if effective_pval > 0:
                effective_pval = effective_pval / args.num_bootstraps
            # generate results
            results['NumCollapsedSNPs'] = len(loci)
            results['NumCandidates'] = len(candidates)
            results['Density'] = emp_density
            results['PValue'] = effective_pval
            results['BSMean'] = bootstraps.mean()
            results['BSStd'] = bootstraps.std()
            results['SNP2GeneMethod'] = args.snp2gene
            # Tack them onto the end of the results data frame 
            results = pd.DataFrame([results])

        results['Ontology'] = ont.name
        results['COB'] = cob.name
        results['Term'] = term.id
        results['NumSNPs'] = len(term.loci)
        results['WindowSize'] = args.candidate_window_size
        results['FlankLimit'] = args.candidate_flank_limit
        results['NumBootstraps'] = args.num_bootstraps

        all_results.append(results)
    
    # Return the results 
    all_results = pd.concat(all_results)
    # Make sure the output directory exists
    all_results.to_csv(args.out,sep='\t',index=None)
