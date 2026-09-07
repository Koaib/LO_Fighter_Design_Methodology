# -*- coding: utf-8 -*-
"""
Created on Sat Feb 28 14:51:12 2026

@author: KK
"""

import numpy as np
import scipy.constants as constants
from mission_leg_class import mission_leg
import matplotlib.pyplot as plt


### -----------------------------  User - defined Functions -------------------------- ###
def Calc_fuel_weight_1 (W0, M1_L_D_cruise1, M1_L_D_combat, M1_L_D_dash, M1_L_D_cruise2, M1_L_D_loiter, T_W, W_S, TSFC_mil, TSFC_wet):  

    R_cruise1 = (650)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (550)*constants.nautical_mile         # nautical miles to m
    R_dash = 100*constants.nautical_mile            # nautical miles to m
    E_combat = 2*constants.minute                   # minute to s
    E_loiter = 20*constants.minute                  # minute to s
    C_cruise1 = TSFC_mil
    C_cruise2 = TSFC_mil
    C_loiter = TSFC_mil
    C_dash = TSFC_wet
    C_combat = TSFC_wet
    
   
   # Establishing fuel fractions & fuel weight for every segment
    W1_W0 = 0.995
    W1 = W1_W0 * W0                                                                   # Takeoff/Catapult launch 
    W2_W1 = (1.0065 - 0.0325*M1_cruise1.M) / (1.0065 -0.0325*M1_catapult_launch.M)
    W2 = W2_W1 * W1                                                                   # Climb 
    W3_W2 = np.exp((-R_cruise1*C_cruise1)/(M1_cruise1.v * M1_L_D_cruise1))              # Cruise 01
    W3 = W3_W2 * W2
    W4_W3 = 1                                                                         # Descent
    W4 = W4_W3 * W3
    W5_W4 = 1 - C_combat* (M1_combat.alpha_max/M1_combat.beta) * T_W * E_combat           # Combat 
    W5 = W5_W4 * W4
    W6_W5 = (0.991 - 0.007*M1_dash.M - 0.01*(M1_dash.M**2)) / (1.0065 - 0.0325*M1_combat.M)   # Climb 
    W6 = W6_W5 * W5  
    W7_W6 = np.exp((-R_dash*C_dash)/(M1_dash.v*M1_L_D_dash))                          # Dash (~ Range Eqn)
    W7 = W7_W6 * W6   
    W8_W7 = (1.0065 - 0.0325*M1_cruise2.M)/(0.991 - 0.007*M1_dash.M - 0.01*(M1_dash.M**2))     # Climb
    W8 = W8_W7 * W7
    W9_W8 = np.exp((-R_cruise2*C_cruise2)/(M1_cruise2.v * M1_L_D_cruise2))               # Cruise 02
    W9 = W9_W8 * W8 
    W10_W9 = 1                                                                  # Descent 
    W10 = W10_W9 * W9
    W11_W10 = np.exp((-E_loiter*C_loiter)/(M1_L_D_loiter))                         # Loiter
    W11 = W11_W10 * W10
    W12_W11 = 0.995                                                                 # Descent for landing
    W12 = W12_W11 * W11
    W13_W12 = 0.997                                                             # Landing/ Recovery
    W13 = W13_W12 * W12
    # Second landing attempt
    W11a = W13
    W12a_W11a = 0.995                                                                 # Descent for landing
    W12a = W12a_W11a * W11a
    W13a_W12a = 0.997                                                             # Landing/ Recovery
    W13a = W13a_W12a * W12a

    # Multiplied by 1.06 to account for trapped and reserved fuel
    Wf = (W0 - W13a) * 1.06   # fuel burned × reserve/trapped fuel factor
    
    print(W2_W1, W3_W2, W4_W3, W5_W4, W6_W5, W7_W6, W8_W7, W9_W8, W10_W9, W11_W10)

    
   # print(f"The fuel weight required for mission 1 is {Wf: .3f} kg \n")
    return Wf


def Calc_fuel_weight_2 (W0, M2_L_D_cruise1, M2_L_D_ingress, M2_L_D_egress, M2_L_D_cruise2, M2_L_D_loiter, T_W, W_S, M2_catapult_launch, M2_cruise1, M2_ingress, M2_egress, M2_cruise2, TSFC_mil, TSFC_wet ):
    
    R_cruise1 = (650)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (650)*constants.nautical_mile         # nautical miles to m
    R_ingress = 50*constants.nautical_mile          # nautical miles to m
    R_egress = 50*constants.nautical_mile           # nautical miles to m
    E_loiter = 20*constants.minute                  # minute to s
    M_ingress_egress = 0.9
    a_ingress_egress = 1116.45*constants.foot       # ft/s to m/s
                                                    # speed of sound at SL
    C_cruise1 = TSFC_mil
    C_cruise2 = TSFC_mil
    C_loiter = TSFC_mil
    C_ingress_egress = TSFC_mil
   
    # Establishing fuel fractions & fuel weight for every segment
    W1_W0 = 0.995
    W1 = W1_W0 * W0                                                                   # Takeoff/Catapult launch 
    W2_W1 = (1.0065 - 0.0325*M2_cruise1.M) / (1.0065 -0.0325*M2_catapult_launch.M)
    W2 = W2_W1 * W1                                                                   # Climb 
    W3_W2 = np.exp((-R_cruise1*C_cruise1)/(M2_cruise1.v*M2_L_D_cruise1))              # Cruise 01
    W3 = W3_W2 * W2
    W4_W3 = 1                                                                         # Descent
    W4 = W4_W3 * W3
    W5_W4 = np.exp((-R_ingress*C_ingress_egress)/(M2_ingress.v * M2_L_D_ingress))      # Ingress
    W5 = W5_W4 * W4
    W6_W5 = 1  
    W6 = W6_W5 * W5                                                                              # Strike 
    W7_W6 = np.exp((-R_egress*C_ingress_egress)/(M2_egress.v *M2_L_D_egress))       # Egress
    W7 = W7_W6 * W6    
    W8_W7 = (1.0065 - 0.0325*M2_cruise2.M) / (1.0065 -0.0325*M2_egress.M)                 # Climb
    W8 = W8_W7 * W7
    W9_W8 = np.exp((-R_cruise2*C_cruise2)/(M2_cruise2.v*M2_L_D_cruise2))                              # Cruise 02
    W9 = W9_W8 * W8
    W10_W9 = 1                                                                               # Descent
    W10 = W10_W9 * W9    
    W11_W10 = np.exp((-E_loiter*C_loiter)/(M2_L_D_loiter))                                      # Loiter
    W11 = W11_W10 * W10
    W12_W11 = 0.995                                                                 # Descent for landing
    W12 = W12_W11 * W11
    W13_W12 = 0.997                                                             # Landing/ Recovery
    W13 = W13_W12 * W12
    # Second landing attempt
    W11a = W13
    W12a_W11a = 0.995                                                                 # Descent for landing
    W12a = W12a_W11a * W11a
    W13a_W12a = 0.997                                                             # Landing/ Recovery
    W13a = W13a_W12a * W12a

    # Multiplied by 1.06 to account for trapped and reserved fuel
    Wf = (W0 - W13a) * 1.26   # fuel burned × reserve/trapped fuel factor


    #print(f"The fuel weight required for mission 2 is {Wf: .3f} kg \n")
    print(W2_W1, W3_W2, W4_W3, W5_W4, W6_W5, W7_W6, W8_W7, W9_W8, W10_W9, W11_W10)

    return Wf

def Calc_Empty_Weight_fraction (W0, T_W, W_S):
    a = -0.02 
    b = 2.16
    C1 = -0.10
    C2 = 0.20
    C3 = 0.04
    C4 = -0.10
    C5 = 0.08
    K_vs = 1
    A = 3.5 
    M = 2
    W0 = W0  / 4.44822     # N → lb
    W_S = W_S / 47.880      # N/m² → lb/ft²

    We_W0 = (a + (b * (W0 ** C1) * (A**C2) * (T_W **C3) * (W_S ** C4) * (M**C5))) * K_vs 
    return We_W0

def calculate_L_D (self, W_S, AR):
    L_D = 1 / ( ((self.q * self.Cd0)/(self.beta * W_S)) + ((self.beta * W_S)/(self.q * np.pi * AR * self.e)) )
    return L_D


def calculate_L_D_combat (self, W_S, AR, n):
    L_D = 1 / ( ((self.q * self.Cd0)/(self.beta *n* W_S)) + ((self.beta *n* W_S)/(self.q * np.pi * AR * self.e)) )
    return L_D

# =============================================
# FIXED ENGINE SIZING - Pratt & Whitney F119
# =============================================

# Engine specs
# N_engines     = 2
# T_mil_lbf     = 26000          # Military (dry) thrust per engine [lbf]
# T_wet_lbf     = 35000          # Wet (afterburner) thrust per engine [lbf]
# TSFC_mil      = 0.71 / 3600    # [1/s]
# TSFC_wet      = 1.70 / 3600    # [1/s]

# T_mil_N = T_mil_lbf * 4.44822  # N per engine
# T_wet_N = T_wet_lbf * 4.44822  # N per engine

# =============================================
# FIXED ENGINE SIZING - F100 PW 232 
# =============================================

# Engine specs
N_engines     = 2
T_mil_lbf     = 20100          # Military (dry) thrust per engine [lbf]
T_wet_lbf     = 32500          # Wet (afterburner) thrust per engine [lbf]
TSFC_mil      = 0.73 / 3600    # [1/s]
TSFC_wet      = 1.94 / 3600    # [1/s]

T_mil_N = T_mil_lbf * 4.44822  # N per engine
T_wet_N = T_wet_lbf * 4.44822  # N per engine


# -----------------------------------------------
# STEP 1: Get T/W from constraint analysis (same as before)
# This is your existing T_W value from the constraint diagram
# -----------------------------------------------
T_W = 1.1   # from your constraint analysis

# -----------------------------------------------
# STEP 2: Fixed W0 from Raymer Eq. 6.25
# W0 = N * T_per_engine / (T/W)
# Use mil or wet thrust depending on takeoff condition
# For carrier takeoff, typically use wet (afterburner) thrust
# -----------------------------------------------
W0_fixed_mission1 = (N_engines * T_wet_N) / T_W
W0_fixed_mission2 = (N_engines * T_wet_N) / T_W

print(f"\n{'='*50}")
print(f"Fixed Engine: P&W F119")
print(f"Total wet thrust: {N_engines * T_wet_N / 1000:.1f} kN")
print(f"Total mil thrust: {N_engines * T_mil_N / 1000:.1f} kN")
print(f"W0 (fixed, from Eq.6.25): {(N_engines * T_wet_N / T_W)/9.81:.1f} kg")
print(f"{'='*50}\n")

# -----------------------------------------------
# STEP 3: Use fixed W0 to calculate fuel weight
# and check if mission is achievable
# (W0 is NOT iterated - it's fixed by the engine)
# -----------------------------------------------
W0_known = N_engines * T_wet_N / T_W   # This is your fixed W0

# Recalculate L/D with same W_S, AR
W_S = 3700
AR  = 3.5
n = 7

W_crew = (200*2) * (1/2.205)                    # lb to kg to N
W_payload_mission1 = (2136 + 376) * (1/2.205)   # lb to N
W_payload_mission2 = (4000 + 376) * (1/2.205)   # lb to N



M1_catapult_launch = mission_leg(1,0.970,0.206,0.14,0.016,1.0594,1) 
#M1_climb_1 = mission_leg(0.955,M,K1,Cd0,temp_r,p_r)
M1_cruise1 = mission_leg(2,0.8379,0.85,0.15,0.022,0.8003,0.236)
#M1_descend_1 = mission_leg(0.8379,M,K1,Cd0,temp_r,p_r)
M1_combat = mission_leg(3,0.8103,0.7,0.14,0.018,0.9854,0.6878)
#M1_climb_2 = mission_leg(0.798,M,K1,Cd0,temp_r,p_r)
M1_dash = mission_leg(4,0.755,1.6,0.5,0.038,0.8373,0.2975)
#M1_climb_3 = mission_leg(0.7437,M,K1,Cd0,temp_r,p_r)
M1_cruise2 = mission_leg(5,0.6619,0.85,0.15,0.022,0.7633,0.1858)
#M1_descend_2 = mission_leg(0.6619,M,K1,Cd0,temp_r,p_r)
M1_loiter = mission_leg(6,0.6493,0.5,0.14,0.016,0.9854,0.6878)
#M1_descend_3 = mission_leg(0.6493,M,K1,Cd0,temp_r,p_r)
#M1_landing = mission_leg(0.6461,M,0.15,0.018,1.0594,1)

M1_L_D_cruise1 = calculate_L_D(M1_cruise1, W_S, AR)
M1_L_D_combat = calculate_L_D_combat(M1_combat, W_S, AR, n)
M1_L_D_dash = calculate_L_D(M1_dash, W_S, AR)
M1_L_D_cruise2 = calculate_L_D(M1_cruise2, W_S, AR)
M1_L_D_loiter = calculate_L_D(M1_loiter, W_S, AR)


M2_catapult_launch=mission_leg(7,0.97,0.206,0.14,0.016,1.0594,1)
#M2_climb_1 = mission_leg(0.955,M,K1,Cd0,temp_r,p_r)
M2_cruise1 = mission_leg(8,0.8379,0.85,0.15,0.022,0.8003,0.2360)
#M2_descend_1 = mission_leg(0.8379,M,K1,Cd0,temp_r,p_r)
M2_ingress = mission_leg(9,0.8287,0.9,0.16,0.023,1.0594,1)
#M2_strike = mission_leg(0.8287,0.9,0.16,0.023,1.0594,1)
M2_egress = mission_leg(10,0.8196,0.9,0.16,0.023,1.0594,1)
#M2_climb_2 = mission_leg(0.8073,M,K1,Cd0,temp_r,p_r)
M2_cruise2 = mission_leg(11,0.7185,0.85,0.15,0.022,0.7633,0.1858)
#M2_descend_2 = mission_leg(0.7185,M,K1,Cd0,temp_r,p_r)
M2_loiter = mission_leg(12,0.7048,0.5,0.14,0.016,0.9854,0.6878)
#M2_descend_3 = mission_leg(0.7048,M,K1,Cd0,temp_r,p_r)
#M2_landing = mission_leg(0.7013,M,0.15,0.018,1.0594,1)

M1_L_D_cruise1 = calculate_L_D(M1_cruise1, W_S, AR)
M1_L_D_combat  = calculate_L_D_combat(M1_combat, W_S, AR, n)
M1_L_D_dash    = calculate_L_D(M1_dash, W_S, AR)
M1_L_D_cruise2 = calculate_L_D(M1_cruise2, W_S, AR)
M1_L_D_loiter  = calculate_L_D(M1_loiter, W_S, AR)

M2_L_D_cruise1 = calculate_L_D(M2_cruise1, W_S, AR)
M2_L_D_ingress = calculate_L_D(M2_ingress, W_S, AR)
M2_L_D_egress  = calculate_L_D(M2_egress, W_S, AR)
M2_L_D_cruise2 = calculate_L_D(M2_cruise2, W_S, AR)
M2_L_D_loiter  = calculate_L_D(M2_loiter, W_S, AR)

# -----------------------------------------------
# STEP 4: Compute fuel weight using fixed W0
# -----------------------------------------------
Wf_m1 = Calc_fuel_weight_1(W0_known, M1_L_D_cruise1, M1_L_D_combat,
                            M1_L_D_dash, M1_L_D_cruise2, M1_L_D_loiter,
                            T_W, W_S, TSFC_mil, TSFC_wet)

Wf_m2 = Calc_fuel_weight_2(W0_known, M2_L_D_cruise1, M2_L_D_ingress,
                            M2_L_D_egress, M2_L_D_cruise2, M2_L_D_loiter,
                            T_W, W_S, M2_catapult_launch, M2_cruise1,
                            M2_ingress, M2_egress, M2_cruise2, TSFC_mil, TSFC_wet)

# -----------------------------------------------
# STEP 5: Check closure (does W0 close?)
# W0_check = We + Wf + Wcrew + Wpayload
# -----------------------------------------------
We_W0_m1 = Calc_Empty_Weight_fraction(W0_known, T_W, W_S)
We_W0_m2 = Calc_Empty_Weight_fraction(W0_known, T_W, W_S)

W0_check_m1 = (W_crew + W_payload_mission1 + Wf_m1 + We_W0_m1 * W0_known)
W0_check_m2 = (W_crew + W_payload_mission2 + Wf_m2 + We_W0_m2 * W0_known)

print(f"--- MISSION 1 ---")
print(f"Fixed W0 (engine-driven):   {W0_known/9.81:.1f} kg")
print(f"Required W0 (from weights): {W0_check_m1/9.81:.1f} kg")
print(f"Closure error M1:           {(W0_check_m1 - W0_known)/9.81:.1f} kg")

print(f"\n--- MISSION 2 ---")
print(f"Fixed W0 (engine-driven):   {W0_known/9.81:.1f} kg")
print(f"Required W0 (from weights): {W0_check_m2/9.81:.1f} kg")
print(f"Closure error M2:           {(W0_check_m2 - W0_known)/9.81:.1f} kg")

# -----------------------------------------------
# STEP 6: Wing area and thrust directly
# -----------------------------------------------
S_ref = W0_known / W_S
T_total = N_engines * T_wet_N

print(f"\nWing Area S = {S_ref:.2f} m²")
print(f"Total Takeoff Thrust (wet) = {T_total/1000:.1f} kN")

# -----------------------------------------------
# RESULTS SUMMARY
# -----------------------------------------------
We_m1 = We_W0_m1 * W0_known
We_m2 = We_W0_m2 * W0_known

print(f"\n{'='*55}")
print(f"{'WEIGHT BREAKDOWN SUMMARY':^55}")
print(f"{'='*55}")
print(f"{'Component':<35} {'Mission 1':>8}  {'Mission 2':>8}")
print(f"{'-'*55}")
print(f"{'Fixed W0 (engine-driven) [kg]':<35} {W0_known/9.81:>8.1f}  {W0_known/9.81:>8.1f}")
print(f"{'Empty Weight Fraction We/W0':<35} {We_W0_m1:>8.4f}  {We_W0_m2:>8.4f}")
print(f"{'Empty Weight We [kg]':<35} {We_m1/9.81:>8.1f}  {We_m2/9.81:>8.1f}")
print(f"{'Fuel Weight Wf [kg]':<35} {Wf_m1/9.81:>8.1f}  {Wf_m2/9.81:>8.1f}")
print(f"{'Crew Weight [kg]':<35} {W_crew:>8.1f}  {W_crew:>8.1f}")
print(f"{'Payload Weight [kg]':<35} {W_payload_mission1:>8.1f}  {W_payload_mission2:>8.1f}")
print(f"{'-'*55}")
print(f"{'Required W0 (from weights) [kg]':<35} {W0_check_m1/9.81:>8.1f}  {W0_check_m2/9.81:>8.1f}")
print(f"{'Closure Error [kg]':<35} {(W0_check_m1-W0_known)/9.81:>+8.1f}  {(W0_check_m2-W0_known)/9.81:>+8.1f}")
print(f"{'='*55}")

print(M1_L_D_cruise1, M1_L_D_cruise2)



