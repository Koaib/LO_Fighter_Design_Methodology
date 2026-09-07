# -*- coding: utf-8 -*-
"""
Created on Tue Jan 20 21:00:22 2026

@author: KK
"""

import numpy as np
import scipy.constants as constants
from mission_leg_class import mission_leg
import matplotlib.pyplot as plt


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
def Calc_fuel_weight_1 (W0, M1_L_D_cruise1, M1_L_D_combat, M1_L_D_dash, M1_L_D_cruise2, M1_L_D_loiter, T_W, W_S):  

    R_cruise1 = (850)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (750)*constants.nautical_mile         # nautical miles to m
    R_dash = 100*constants.nautical_mile            # nautical miles to m
    E_combat = 5*constants.minute                   # minute to s
    E_loiter = 20*constants.minute                  # minute to s
    C_cruise1 = 1.08/3600
    C_cruise2 = 1.06/3600
    C_loiter = 1.16/3600
    C_dash = 1.88/3600
    C_combat = 1.80/3600
    
   
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
    Wf = (W0-W13a)*1.26
    
   # print(f"The fuel weight required for mission 1 is {Wf: .3f} kg \n")
    return Wf


def Calc_fuel_weight_2 (W0, M2_L_D_cruise1, M2_L_D_ingress, M2_L_D_egress, M2_L_D_cruise2, M2_L_D_loiter, T_W, W_S, M2_catapult_launch, M2_cruise1, M2_ingress, M2_egress, M2_cruise2 ):
    
    R_cruise1 = (850)*constants.nautical_mile         # nautical miles to m
    R_cruise2 = (850)*constants.nautical_mile         # nautical miles to m
    R_ingress = 50*constants.nautical_mile          # nautical miles to m
    R_egress = 50*constants.nautical_mile           # nautical miles to m
    E_loiter = 20*constants.minute                  # minute to s
    M_ingress_egress = 0.9
    a_ingress_egress = 1116.45*constants.foot       # ft/s to m/s
                                                    # speed of sound at SL
    C_cruise1 = 1.08/3600
    C_cruise2 = 1.06/3600
    C_loiter = 1.16/3600
    C_ingress_egress = 1.22/3600
   
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
    Wf = (W0-W13a)*1.26

    #print(f"The fuel weight required for mission 2 is {Wf: .3f} kg \n")
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
    W0  = W0  / 4.44822     # N → lb
    W_S = W_S / 47.880      # N/m² → lb/ft²

    We_W0 = (a + (b * (W0 ** C1) * (A**C2) * (T_W **C3) * (W_S ** C4) * (M**C5))) * K_vs 
    return We_W0

def calculate_L_D (self, W_S, AR):
    L_D = 1 / ( ((self.q * self.Cd0)/(self.beta * W_S)) + ((self.beta * W_S)/(self.q * np.pi * AR * self.e)) )
    return L_D


def calculate_L_D_combat (self, W_S, AR, n):
    L_D = 1 / ( ((self.q * self.Cd0)/(self.beta *n* W_S)) + ((self.beta *n* W_S)/(self.q * np.pi * AR * self.e)) )
    return L_D

def update_S_and_T_by_converged_W0 (W_S, T_W, W0_mission1, W0_mission2):
    W0 = max (W0_mission1, W0_mission2)
    T = T_W * W0
    S = W0 / W_S
    print (f"The value of Thrust (SL) is {T:.1f} N and Wing Area is {S:.1f} sq. m")
    return T, S

### ----------------------------- MAIN EXECUTION -------------------------- ###

W0 = 31828.34*9.81
T_W = 1.27
W_S = 4450
AR = 3.5
n = 7

M1_catapult_launch = mission_leg(1,0.970,0.206,0.14,0.016,1.0594,1) 
#M1_climb_1 = mission_leg(0.955,M,K1,Cd0,temp_r,p_r)
M1_cruise1 = mission_leg(2,0.8379,0.85,0.15,0.022,0.8003,0.236)
#M1_descend_1 = mission_leg(0.8379,M,K1,Cd0,temp_r,p_r)
M1_combat = mission_leg(3,0.8103,0.7,0.14,0.018,0.9854,0.6878)
#M1_climb_2 = mission_leg(0.798,M,K1,Cd0,temp_r,p_r)
M1_dash = mission_leg(4,0.755,2,0.5,0.038,0.8373,0.2975)
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

M2_L_D_cruise1 = calculate_L_D(M2_cruise1, W_S, AR)
M2_L_D_ingress = calculate_L_D(M2_ingress, W_S, AR)
M2_L_D_egress = calculate_L_D(M2_egress, W_S, AR)
M2_L_D_cruise2 = calculate_L_D(M2_cruise2, W_S, AR)
M2_L_D_loiter = calculate_L_D(M2_loiter, W_S, AR)

W_crew = (200*2) * 4.448                          # lb to kg
W_payload_mission1 = (2500 + 2136 + 376) * 4.448  # lb to kg
W_payload_mission2 = (2500 + 4000 + 376) * 4.448  # lb to kg
tol = 0.1

# --- Convergence tracking (ADD THIS) ---

# Mission 1 history
W0_hist_m1 = []
err_hist_m1 = []

# Mission 2 history
W0_hist_m2 = []
err_hist_m2 = []



# Mission 1
# First iterations
W0_guess = W0
We_W0 = Calc_Empty_Weight_fraction(W0_guess, T_W, W_S)
Wf_mission_1 = Calc_fuel_weight_1(W0_guess, M1_L_D_cruise1, M1_L_D_combat, M1_L_D_dash, M1_L_D_cruise2, M1_L_D_loiter, T_W, W_S)
W0_mission1 = (W_crew + W_payload_mission1 + Wf_mission_1 + We_W0 * W0_guess)

# # --- ADD INSIDE Mission 1 (after computing W0_mission1 each time) ---
# W0_hist_m1.append(W0_mission1)
# err_hist_m1.append(abs(W0_mission1 - W0_guess))


# print (f"TOGW after first iteration for first mission is = {W0_mission1/9.81:.2f} kg")

# # Loop iteration
# while abs(W0_mission1 - W0_guess) > tol:
#     W0_guess = W0_mission1
#     We_W0 = Calc_Empty_Weight_fraction(W0_guess, T_W, W_S)
#     Wf_mission_1 = Calc_fuel_weight_1(W0_guess, M1_L_D_cruise1, M1_L_D_combat, M1_L_D_dash, M1_L_D_cruise2, M1_L_D_loiter, T_W, W_S)
#     W0_mission1 = (W_crew + W_payload_mission1 + Wf_mission_1 + We_W0 * W0_guess)
    
#     # --- ADD INSIDE Mission 1 (after computing W0_mission1 each time) ---
#     W0_hist_m1.append(W0_mission1)
#     err_hist_m1.append(abs(W0_mission1 - W0_guess))

    
    
print(f"The empty weight fraction for mission 1 is = {We_W0:.2f}")
print(f"The fuel weight required for mission 1 is {Wf_mission_1/9.81: .2f} kg \n")
print(f"Converged W0 from mission 1 is = {W0_mission1/9.81:.2f} kg")




# Mission 2
# First iterations
W0_guess = W0
We_W0 = Calc_Empty_Weight_fraction(W0_guess, T_W, W_S)
Wf_mission_2 = Calc_fuel_weight_2(W0_guess, M2_L_D_cruise1, M2_L_D_ingress, M2_L_D_egress, M2_L_D_cruise2, M2_L_D_loiter, T_W, W_S, M2_catapult_launch, M2_cruise1, M2_ingress, M2_egress, M2_cruise2)
W0_mission2 = (W_crew + W_payload_mission2 + Wf_mission_2 + We_W0 * W0_guess)

# # --- ADD INSIDE Mission 2 (after computing W0_mission2 each time) ---
# W0_hist_m2.append(W0_mission2)
# err_hist_m2.append(abs(W0_mission2 - W0_guess))


# print (f"TOGW after first iteration for second mission is = {W0_mission2/9.81:.2f} kg")
# # Loop iteration
# while abs(W0_mission2 - W0_guess) > tol:
#     W0_guess = W0_mission2
#     We_W0 = Calc_Empty_Weight_fraction(W0_guess, T_W, W_S)
#     Wf_mission_2 = Calc_fuel_weight_2(W0_guess, M2_L_D_cruise1, M2_L_D_ingress, M2_L_D_egress, M2_L_D_cruise2, M2_L_D_loiter, T_W, W_S, M2_catapult_launch, M2_cruise1, M2_ingress, M2_egress, M2_cruise2)
#     W0_mission2 = (W_crew + W_payload_mission2 + Wf_mission_2 + We_W0 * W0_guess)
    
    
#     # --- ADD INSIDE Mission 2 (after computing W0_mission2 each time) ---
#     W0_hist_m2.append(W0_mission2)
#     err_hist_m2.append(abs(W0_mission2 - W0_guess))

    
print(f"The empty weight fraction for mission 2 is = {We_W0:.2f}")
print(f"The fuel weight required for mission 2 is {Wf_mission_2/9.81: .3f} kg \n")
print(f"Converged W0 from mission 2 is = {W0_mission2/9.81:.2f} kg")

[T,W] = update_S_and_T_by_converged_W0 (W_S, T_W, W0_mission1, W0_mission2)


# --- Convergence plots (ADD AT THE END) ---
plt.figure()
plt.plot(W0_hist_m1, label='Mission 1')
plt.plot(W0_hist_m2, label='Mission 2')
plt.xlabel('Iteration')
plt.ylabel('Take-Off Gross Weight (kg)')
plt.title('TOGW Convergence History')
plt.grid(True)
plt.legend()
plt.show()

plt.figure()
plt.semilogy(err_hist_m1, label='Mission 1')
plt.semilogy(err_hist_m2, label='Mission 2')
plt.xlabel('Iteration')
plt.ylabel('|W0(k+1) - W0(k)|')
plt.title('Iteration Error Convergence')
plt.grid(True, which='both')
plt.legend()
plt.show()

# class mission_leg:
#     def __init__(self, case_id, beta, M, K1, Cd0, temp_r, p_r):
#         self.case_id = case_id
#         self.beta =beta 
#         self.K1= K1
#         self.M = M
#         self.Cd0 = Cd0
#         self.temp_r=temp_r
#         self.p_r=p_r
#         self.sigma=p_r/temp_r;
#         density_std=1.225; 
#         self.density=(density_std*p_r)/temp_r;
#         self.alpha_mil=0.72*(0.88 + 0.245*(np.abs(M-0.6))**1.4)*self.sigma**0.7;
#         self.alpha_max=(0.94 + 0.38*(M-0.4)**2)*self.sigma**0.7;
#         a_std=340.3;
#         self.a=a_std*(self.temp_r)**0.5;
#         self.v=M*self.a;
#         self.q=0.5*self.density*self.v**2;
#         A=3.5;
#         if 0 < M < 1:
#             e = (4.61*(1-(0.045)*A**0.68)*((math.cos(0.8726))**0.15))-3.1
#         else:
#             K = ((A*(M**2 - 1))*(math.cos(0.8726)))/((4*A*(M**2-1)**0.5)-2)
#             e = 1/(math.pi * A * K)
#         self.e = e

print (M1_catapult_launch.v)
            
                 