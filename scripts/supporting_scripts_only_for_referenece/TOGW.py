# -*- coding: utf-8 -*-
"""
Created on Mon Dec  8 10:37:02 2025

@author: KK
"""
import numpy as np
import scipy.constants as constants
#import matplotlib.pyplot as plt
#from scipy.optimize import curve_fit

# Estimation of Design TOGW

### -----  Mission Profile # 1 ----- ###
# 0  - 1  : Catapult launch
# 1  - 2  : Climb
# 2  - 3  : Cruise 01 (cruise out)
# 3  - 4  : Descend
# 4  - 5  : Combat
# 5  - 6  : Climb
# 6  - 7  : Dash
# 7  - 8  : Climb
# 8  - 9  : Cruise 02 (cruise back)
# 9  - 10 : Descend
# 10 - 11 : Loiter
# 11 - 12 : Descend
# 12 - 13 : Landing

### -----  Mission Profile # 2 ----- ###
# 0  - 1  : Catapult launch
# 1  - 2  : Climb
# 2  - 3  : Cruise 01 (cruise out)
# 3  - 4  : Descend
# 4  - 5  : Ingress
# 5  - 6  : Strike
# 6  - 7  : Egress
# 7  - 8  : Climb
# 8  - 9  : Cruise 02 (cruise back)
# 9  - 10 : Descend
# 10 - 11 : Loiter
# 11 - 12 : Descend
# 12 - 13 : Landing

# V_cruise input in knots
# Ranges input in nautical miles
# Endurance input in minutes

### -----------------------------  User - defined Functions -------------------------- ###

def Calc_AR_by_book():
    # These values are for our case
    a = 5.416
    C = -0.622
    M_max = 2
    
    AR = a * (M_max**C)             # Pg 78 Raymer
    return AR


def Calc_L_D_max(AR):
    
    # These values are for our case
    K_LD = 14                           # for military jets
    S_ratio = 4.5                       # figure 3.6
    
    L_D_max = K_LD * (AR/S_ratio)**0.5  # Pg 40 Raymer
    return L_D_max


def Calc_Empty_Weight_fraction_by_book (W0):
    # These values are for our case
    # Table 3.1, pg 31, Jet Fighter
    A = 2.11
    C = -0.13
    K_vs = 1
    We_W0 = A * K_vs * (W0 **C)
    return We_W0


def Calc_Empty_Weight_fraction_by_own_trendline (W0):
    We_W0 = 0.6597 * (W0 ** -0.0024)
    return We_W0


def Calc_fuel_fraction_1 (L_D_max, V_cruise):  
    # These values are for our case
    R_cruise1 = (850-75)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (750-75)*constants.nautical_mile         # nautical miles to m
    R_dash = 100*constants.nautical_mile            # nautical miles to m
    E_combat = 5*constants.minute                   # minute to s
    E_loiter = 20*constants.minute                  # minute to s
    M_dash = 2 
    a_dash_altitude = 994.85*constants.foot         # ft/s to m/s
                                                    # speed of sound at 30,000 ft  
    # For turbofan and jet and supersonic dash and combat assumptions
    C_cruise = 0.8/3600
    C_loiter = 0.7/3600
    C_dash = 4.8314e-4
    C_combat = 4.8314e-4
    L_D_cruise = 0.866 * L_D_max
    L_D_loiter = L_D_max
    L_D_dash = 0.25*L_D_cruise
    L_D_combat = 0.4*L_D_cruise
    V_cruise = V_cruise * constants.knot
    V_dash = M_dash * a_dash_altitude

    # Establishing fuel fractions for every segment
    W1_W0 = 0.970                                                               # Takeoff/Catapult launch 
    W2_W1 = 0.985                                                               # Climb 
    W3_W2 = np.exp((-R_cruise1*C_cruise)/(V_cruise*L_D_cruise))                 # Cruise 01
    W4_W3 = 1                                                                   # Descent
    W5_W4 = np.exp((-E_combat*C_combat)/(L_D_combat))                           # Combat (~ Endurance Eqn)
    W6_W5 = 0.985                                                               # Climb 
    W7_W6 = np.exp((-R_dash*C_dash)/(V_dash*L_D_dash))                          # Dash (~ Range Eqn)
    W8_W7 = 0.985                                                               # Climb
    W9_W8 = np.exp((-R_cruise2*C_cruise)/(V_cruise*L_D_cruise))                 # Cruise 02
    W10_W9 = 1                                                                  # Descent
    W11_W10 = np.exp((-E_loiter*C_loiter)/(L_D_loiter))                         # Loiter
    W12_W11 = 1                                                                 # Descent
    W13_W12 = 0.995                                                             # Landing/ Recovery
    
    # Multiplied by 1.06 to account for trapped and reserved fuel
    Wf_W0 = (1 - W1_W0*W2_W1*W3_W2*W4_W3*W5_W4*W6_W5*W7_W6*W8_W7*W9_W8*W10_W9*W11_W10*W12_W11*W13_W12)*1.06
    
    print("The fuel fractions calculated/estimated for each segment are as follows:\n")
    print(f"0  - 1  : Catapult Launch       | W1/W0  = {W1_W0:.3f}")
    print(f"1  - 2  : Climb                 | W2/W1  = {W2_W1:.3f}")
    print(f"2  - 3  : Cruise 01 (Out)       | W3/W2  = {W3_W2:.3f}")
    print(f"3  - 4  : Descend               | W4/W3  = {W4_W3:.3f}")
    print(f"4  - 5  : Combat                | W5/W4  = {W5_W4:.3f}")
    print(f"5  - 6  : Climb                 | W6/W5  = {W6_W5:.3f}")
    print(f"6  - 7  : Dash                  | W7/W6  = {W7_W6:.3f}")
    print(f"7  - 8  : Climb                 | W8/W7  = {W8_W7:.3f}")
    print(f"8  - 9  : Cruise 02 (Back)      | W9/W8  = {W9_W8:.3f}")
    print(f"9  - 10 : Descend               | W10/W9 = {W10_W9:.3f}")
    print(f"10 - 11 : Loiter                | W11/W10 = {W11_W10:.3f}")
    print(f"11 - 12 : Descend               | W12/W11 = {W12_W11:.3f}")
    print(f"12 - 13 : Landing               | W13/W12 = {W13_W12:.3f} \n")
    print(f"The fuel weight fraction (Wf/W0) for mission 1 is {Wf_W0: .3f} \n")
    
    return Wf_W0


def Calc_fuel_fraction_2 (L_D_max, V_cruise):
    
    # These values are for our case
    R_cruise1 = (850-75)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (750-75)*constants.nautical_mile         # nautical miles to m
    R_ingress = 50*constants.nautical_mile          # nautical miles to m
    R_egress = 50*constants.nautical_mile           # nautical miles to m
    E_loiter = 20*constants.minute                  # minute to s
    M_ingress_egress = 0.9
    a_ingress_egress = 1116.45*constants.foot       # ft/s to m/s
                                                    # speed of sound at SL
    # For turbofan and jet subsomic dash and strike assumptions
    C_cruise = 0.8/3600
    C_loiter = 0.7/3600
    C_ingress_egress = 2.3422e-4
    L_D_cruise = 0.866 * L_D_max
    L_D_loiter = L_D_max
    L_D_ingress_egress = 0.6*L_D_cruise
    
    V_cruise = V_cruise * constants.knot
    V_ingress_egress = M_ingress_egress * a_ingress_egress

    # Establishing fuel fractions for every segment
    W1_W0 = 0.970                                                                            # Takeoff/Catapult launch 
    W2_W1 = 0.985                                                                            # Climb 
    W3_W2 = np.exp((-R_cruise1*C_cruise)/(V_cruise*L_D_cruise))                              # Cruise 01
    W4_W3 = 1                                                                                # Descent
    W5_W4 = np.exp((-R_ingress*C_ingress_egress)/(V_ingress_egress*L_D_ingress_egress))      # Ingress
    W6_W5 = 1                                                                                # Strike 
    W7_W6 = np.exp((-R_egress*C_ingress_egress)/(V_ingress_egress*L_D_ingress_egress))       # Egress
    W8_W7 = 0.985                                                                            # Climb
    W9_W8 = np.exp((-R_cruise2*C_cruise)/(V_cruise*L_D_cruise))                              # Cruise 02
    W10_W9 = 1                                                                               # Descent
    W11_W10 = np.exp((-E_loiter*C_loiter)/(L_D_loiter))                                      # Loiter
    W12_W11 = 1                                                                              # Descent
    W13_W12 = 0.995                                                                          # Landing/ Recovery
    
    # Multiplied by 1.06 to account for trapped and reserved fuel
    Wf_W0 = (1 - W1_W0*W2_W1*W3_W2*W4_W3*W5_W4*W6_W5*W7_W6*W8_W7*W9_W8*W10_W9*W11_W10*W12_W11*W13_W12)*1.06
    
    print("The fuel fractions calculated/estimated for each segment are as follows:\n")
    print(f"0  - 1  : Catapult Launch       | W1/W0  = {W1_W0:.3f}")
    print(f"1  - 2  : Climb                 | W2/W1  = {W2_W1:.3f}")
    print(f"2  - 3  : Cruise 01 (Out)       | W3/W2  = {W3_W2:.3f}")
    print(f"3  - 4  : Descend               | W4/W3  = {W4_W3:.3f}")
    print(f"4  - 5  : Ingress               | W5/W4  = {W5_W4:.3f}")
    print(f"5  - 6  : Strike                | W6/W5  = {W6_W5:.3f}")
    print(f"6  - 7  : Egress                | W7/W6  = {W7_W6:.3f}")
    print(f"7  - 8  : Climb                 | W8/W7  = {W8_W7:.3f}")
    print(f"8  - 9  : Cruise 02 (Back)      | W9/W8  = {W9_W8:.3f}")
    print(f"9  - 10 : Descend               | W10/W9 = {W10_W9:.3f}")
    print(f"10 - 11 : Loiter                | W11/W10 = {W11_W10:.3f}")
    print(f"11 - 12 : Descend               | W12/W11 = {W12_W11:.3f}")
    print(f"12 - 13 : Landing               | W13/W12 = {W13_W12:.3f} \n")
    print(f"The fuel weight fraction (Wf/W0) for mission 2 is {Wf_W0: .3f} \n")
    
    return Wf_W0


### ----------------------------- MAIN EXECUTION -------------------------- ###

W_crew = (200*2) * (1/2.205)                          # lb to kg
W_payload_mission1 = (2500 + 2136 + 376) * (1/2.205)  # lb to kg
W_payload_mission2 = (2500 + 4000 + 376) * (1/2.205)  # lb to kg
V_cruise = 482      # knots
AR = Calc_AR_by_book()
L_D_max = Calc_L_D_max(AR)
tol = 0.1

# Mission 1 & 2 fuel fraction 
Wf_W0_mission_1 = Calc_fuel_fraction_1(L_D_max, V_cruise)
Wf_W0_mission_2 = Calc_fuel_fraction_2(L_D_max, V_cruise)

# Mission 1
# First iterations
W0_guess = 80000
We_W0 = Calc_Empty_Weight_fraction_by_book(W0_guess)
W0_mission1 = (W_crew + W_payload_mission1) / (1 - Wf_W0_mission_1 - We_W0)
# Loop iteration
while abs(W0_mission1 - W0_guess) > tol:
    W0_guess = W0_mission1
    We_W0 = Calc_Empty_Weight_fraction_by_book(W0_guess)
    W0_mission1 = (W_crew + W_payload_mission1) / (1 - Wf_W0_mission_1 - We_W0)
    
print(f"The empty weight fraction for mission 1 is = {We_W0:.2f}")
print(f"Converged W0 from mission 1 is = {W0_mission1:.2f} kg\n")


# Mission 2
# First iterations
W0_guess = 80000
We_W0 = Calc_Empty_Weight_fraction_by_book(W0_guess)
W0_mission2 = (W_crew + W_payload_mission2) / (1 - Wf_W0_mission_2 - We_W0)
# Loop iteration
while abs(W0_mission2 - W0_guess) > tol:
    W0_guess = W0_mission2
    We_W0 = Calc_Empty_Weight_fraction_by_book(W0_guess)
    W0_mission2 = (W_crew + W_payload_mission1) / (1 - Wf_W0_mission_2 - We_W0)

print(f"The empty weight fraction for mission 2 is = {We_W0:.2f}")
print(f"Converged W0 from mission 2 is = {W0_mission2:.2f} kg")


#print(0.866*L_D_max)
 
