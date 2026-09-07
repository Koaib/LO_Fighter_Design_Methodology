# -*- coding: utf-8 -*-
"""
Created on Thu Jan 22 21:19:52 2026

@author: KK
"""

# all standard values are taken in SI unit

import numpy as np
import math

class mission_leg:
    def __init__(self, case_id, beta, M, K1, Cd0, temp_r, p_r):
        self.case_id = case_id
        self.beta =beta 
        self.K1= K1
        self.M = M
        self.Cd0 = Cd0
        self.temp_r=temp_r
        self.p_r=p_r
        self.sigma=p_r/temp_r;
        density_std=1.225; 
        self.density=(density_std*p_r)/temp_r;
        self.alpha_mil=0.72*(0.88 + 0.245*(np.abs(M-0.6))**1.4)*self.sigma**0.7;
        self.alpha_max=(0.94 + 0.38*(M-0.4)**2)*self.sigma**0.7;
        a_std=340.3;
        self.a=a_std*(self.temp_r)**0.5;
        self.v=M*self.a;
        self.q=0.5*self.density*self.v**2;
        A=3.5;
        if 0 < M < 1:
            e = (4.61*(1-(0.045)*A**0.68)*((math.cos(0.8726))**0.15))-3.1
        else:
            K = ((A*(M**2 - 1))*(math.cos(0.8726)))/((4*A*(M**2-1)**0.5)-2)
            e = 1/(math.pi * A * K)
        self.e = e
            
                 