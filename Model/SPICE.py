import numpy as np
from cvxopt import solvers, matrix
#from QPP import quadprog_solve_qp

# -*- coding: utf-8 -*-
"""
Created on Sun Jan 21 21:52:00 2018

@author: weihuang.xu, Caleb Robey
"""
"""
This product is Copyright (c) 2013 University of Missouri and University
of Florida
All rights reserved.

SPICE Sparsity Promoting Iterated Constrained Endmembers Algorithm
      Finds Endmembers and Unmixes Input Data

Syntax: [endmembers, P] = SPICE(inputData, parameters)

Author: Alina Zare
University of Missouri, Electrical and Computer Engineering
Email Address: azare@ufl.edu
Created: August 2006
Latest Revision: November 22, 2011
This product is Copyright (c) 2013 University of Missouri and University
of Florida
All rights reserved.
"""


class SPICEParameters():
    
    def __init__(self):
        self.u = 0.001  #Trade-off parameter between RSS and V term
        self.gamma = 5  #Sparsity parameter
        self.M = 20  #Initial number of endmembers
        self.endmemberPruneThreshold = 1e-9
        self.changeThresh = 1e-4  #Used as the stopping criterion
        self.iterationCap = 5000 #Alternate stopping criterion
        self.produceDisplay = 1
        self.initEM = None  #This randomly selects parameters.M initial endmembers from the input data
        self.qp_solver = 'cvxopt' #or QPP
        self.prescale = True  # set to normalize SPICE input between 0 and 1


def SPICE(inputData, parameters):
    """"SPICE.
    Inputs:
    inputData           = NxM matrix of M data points of dimensionality N (i.e.  M pixels with N spectral bands, each
                          pixel is a column vector)
    parameters          = The object that contains the following fields:
                          1. u : Regularization Parameter for RSS and V terms
                          2. gamma: Gamma Constant for SPT term
                          3. changeThresh: Stopping Criteria, Change threshold
                              for Objective Function.
                          4. M: Initial Number of endmembers
                          5. iterationCap: Maximum number of iterations
                          6. endmemberPruneThreshold: Proportion threshold used
                             to prune endmembers
                          7. produceDisplay : Set to 1 if a progress display is
                              wanted
                          8. initEM: Set to nan to randomly select endmembers,
                              otherwise NxM matrix of M endmembers with N spectral
                              bands, Number of endmembers must equal parameters.M
    Returns:
    endmembers        = NxM matrix of M endmembers with N spectral bands
    P                 = NxM matrix of abundances corresponding to M input pixels and N endmembers

    :param inputData: float numpy array
    :param parameters: SPICEParameters object
    :return endmembers: float numpy array
    :return P: float numpy array

    """
    base_params = SPICEParameters()
    base_params.__dict__.update(parameters.__dict__)
    parameters = base_params

    parameters.pruningIteration = 1
    M = parameters.M
    X = inputData

    # prescale the data between 0 and 1
    if parameters.prescale:
        prescaler = X.max()
        X /= prescaler

    if parameters.initEM is None:
        # Find Random Initial Endmembers
        randIndices = np.random.permutation(X.shape[1])
        randIndices = randIndices[0:parameters.M]
        endmembers = X[:,randIndices]
        parameters.initEM = endmembers

    else:
        # Use endmembers provided
        M = parameters.initEM.shape[1]
        endmembers = parameters.initEM
    
    # chose unmixing implementation
    if parameters.qp_solver == 'cvxopt':
        unmix = unmix_cvxopt
    else:
        unmix = unmix_qpp


    # N is the number of pixels, RSSreg is the current objective function total.
    N = X.shape[1]
    RSSreg = np.inf
    change = np.inf
    
    iteration = 0
    # initialize proportion map
    P = np.ones((N,M))*(1/M)
    lamb = N*parameters.u/((M-1)*(1-parameters.u))
    Im = np.eye(M)
    I1 = np.ones((M,1))
    
    while((change > parameters.changeThresh) and (iteration < parameters.iterationCap)):
        
        iteration = iteration + 1

        # Given Endmembers, minimize P -- Quadratic Programming Problem
        P = unmix(X, endmembers, parameters.gamma, P)
        
        # Given P minimize Endmembers
        endmembersPrev = endmembers
        endmembers = (np.linalg.inv(P.T@P + lamb*(Im - (I1@I1.T)/M)) @ (P.T @ X.T)).T
                                    
        
        # Prune Endmembers below pruning threshold
        pruneFlag = 0
       
        pruneIndex = (P.max(0)<parameters.endmemberPruneThreshold)*1
        minmaxP = P.max(0).min()

        if(sum(pruneIndex) > 0):
            pruneFlag = 1
            
            endmembers = endmembers[:,np.where(pruneIndex==0)].squeeze()
            P = P[:, np.where(pruneIndex==0)].squeeze()
            M = M - sum(pruneIndex)
            lamb = N*parameters.u/((M-1)*(1-parameters.u))
            Im = np.eye(M)
            I1 = np.ones((M,1))
        
        # Calculate RSSreg (the current objective function value)
        
        sqerr = X - (endmembers @ P.T)
        sqerr = np.power(sqerr, 2) 
        RSS = sum(sum(sqerr))
        V = sum(sum(np.multiply(endmembers,endmembers),2) - (1/M)*np.multiply(sum(endmembers,2),2)/(M-1))
        SPT = M*parameters.gamma
        RSSprev = RSSreg
        RSSreg = (1-parameters.u)*(RSS/N) + parameters.u*V + SPT
        
        # Determine if Change Threshold has been reached
        change = (abs(RSSreg - RSSprev))
    
        if(parameters.produceDisplay):
            print(' ')
            print('Change in Objective Function Value: {}'.format(change))
            print('Minimum of Maximum Proportions: {}'.format(minmaxP))
            print('Number of Endmembers: {}'.format(M))
            print('Iteration: {}'.format(iteration))
            print(' ')

    # rescale the endmember to the original values
    if parameters.prescale:
        endmembers *= prescaler
    
    return endmembers, P


"""
unmix finds an accurate estimation of the proportions of each endmember

Syntax: P2 = unmix(data, endmembers, gammaConst, P)

This product is Copyright (c) 2013 University of Missouri and University
of Florida
All rights reserved.

CVXOPT package is used here. Parameters H,F,L,K,Aeq,beq are corresbonding to 
P,q,G,h,A,B, respectively. lb and ub are element-wise bound constraints which 
are added to matrix G and h respectively.
"""


def unmix_cvxopt(data, endmembers, gammaConst=0, P=None):
    """unmix

    Inputs:
    data            = DxN matrix of N data points of dimensionality D 
    endmembers      = DxM matrix of M endmembers with D spectral bands
    gammaConst      = Gamma Constant for SPT term
    P               = NxM matrix of abundances corresponding to N input pixels and M endmembers

    Returns:
    P2              = NxM matrix of new abundances corresponding to N input pixels and M endmembers
    """

    solvers.options['show_progress'] = False
    X = data  
    M = endmembers.shape[1]  # number of endmembers # endmembers should be column vectors
    N = X.shape[1]  # number of pixels
     # Equation constraint Aeq*x = beq
    # All values must sum to 1 (X1+X2+...+XM = 1)
    Aeq = np.ones((1, M))
    beq = np.ones((1, 1))
     # Boundary Constraints ub >= x >= lb
    # All values must be greater than 0 (0 ? X1,0 ? X2,...,0 ? XM)
    lb = 0
    ub = 1
    g_lb = np.eye(M) * -1
    g_ub = np.eye(M)
    
    # import pdb; pdb.set_trace()

    G = np.concatenate((g_lb, g_ub), axis=0)
    h_lb = np.ones((M, 1)) * lb
    h_ub = np.ones((M, 1)) * ub
    h = np.concatenate((h_lb, h_ub), axis=0)

    if P is None:
        P = np.ones((M, 1)) / M

    gammaVecs = np.divide(gammaConst, sum(P))
    H = 2 * (endmembers.T @ endmembers)
    cvxarr = np.zeros((N,M))
    for i in range(N):
        F = ((np.transpose(-2 * X[:, i]) @ endmembers) + gammaVecs).T
        cvxopt_ans = solvers.qp(P=matrix(H), q=matrix(F), G=matrix(G), h=matrix(h), A=matrix(Aeq), b=matrix(beq))
        cvxarr[i, :] = np.array(cvxopt_ans['x']).T
    cvxarr[cvxarr < 0] = 0
    return cvxarr

def unmix_qpp(data, endmembers, gammaConst=0, P=None):
    
    X = data  #endmembers should be column vectors
    M = endmembers.shape[1]  #number of endmembers
    N = X.shape[1]  #number of pixels
    
    #Equation constraint Aeq*x = beq
    #All values must sum to 1 (X1+X2+...+XM = 1)
    Aeq = np.ones((1, M))
    beq = np.ones((1, 1))
    
    #Boundary Constraints ub >= x >= lb
    #All values must be greater than 0 (0 ? X1,0 ? X2,...,0 ? XM)
    lb = 0
    ub = 1
    g_lb = np.eye(M)*-1
    g_ub = np.eye(M)
    #import pdb; pdb.set_trace()
    G = np.concatenate((g_lb,g_ub), axis=0)
    h_lb = np.ones((M, 1))*lb
    h_ub = np.ones((M, 1))*ub
    h = np.concatenate((h_lb,h_ub),axis=0)
    if P is None:
        P = np.ones((M,1))/M
    gammaVecs = np.divide(gammaConst,sum(P))
    
    H = 2 * (endmembers.T @ endmembers)
    P2 = np.zeros((N, M))
    for i in range(N):
        F = ((np.transpose(-2*X[:,i]) @ endmembers)+gammaVecs).T
        qpas_ans = quadprog_solve_qp(P=H, q=F, G=G, h=h.T, A=Aeq, b=beq.T, initvals=None)
        P2[i,:] = qpas_ans
    
    P2[P2<0] = 0
    
    return P2 
from numpy import hstack, vstack
from quadprog import solve_qp

def quadprog_solve_qp(P, q, G=None, h=None, A=None, b=None, initvals=None):
    """
    Solve a Quadratic Program defined as:
        minimize
            (1/2) * x.T * P * x + q.T * x
        subject to
            G * x <= h
            A * x == b
    using quadprog <https://pypi.python.org/pypi/quadprog/>.
    Parameters
    ----------
    P : numpy.array
        Symmetric quadratic-cost matrix.
    q : numpy.array
        Quadratic-cost vector.
    G : numpy.array
        Linear inequality constraint matrix.
    h : numpy.array
        Linear inequality constraint vector.
    A : numpy.array, optional
        Linear equality constraint matrix.
    b : numpy.array, optional
        Linear equality constraint vector.
    initvals : numpy.array, optional
        Warm-start guess vector (not used).
    Returns
    -------
    x : numpy.array
        Solution to the QP, if found, otherwise ``None``.
    Note
    ----
    The quadprog solver only considers the lower entries of `P`, therefore it
    will use a wrong cost function if a non-symmetric matrix is provided.
    """
    if initvals is not None:
        print("quadprog: note that warm-start values ignored by wrapper")
    qp_G = P
    qp_a = -q
    if A is not None:
        qp_C = -vstack([A, G]).T
        qp_b = -hstack([b, h]).squeeze(0)
        meq = A.shape[0]
    else:  # no equality constraint
        qp_C = -G.T
        qp_b = -h
        meq = 0
    
    return solve_qp(qp_G, qp_a, qp_C, qp_b, meq)[0]