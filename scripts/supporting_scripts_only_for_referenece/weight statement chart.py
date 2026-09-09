import numpy
import math
#weight estimation
# weight for wing
# K_dw=1             #from book section 15.3
# K_vs=1
W_togw=59070.659#from book 
W_dg=W_togw-0.45*(37632.908)
#print("wdg=",W_dg)
N_z=10.5           #ultimate load factor
# S_w=960.1408       #trapezoidal wing area in ft square
# A=3.5              #wing aspect ratio
# tc_r=0.06          #thickness to chord ratio at root
# tp_r=0.2           #taper ratio of wing 
# swp=0.523599       #quarter chord sweep of wing in radian
# S_csw=             #control surface area(wing mounted,includes flaps),ft square,((0.78*Sref)+ (Aileron surface area)*2)

# W_wing=0.0103*K_dw*K_vs*((W_dg*N_z)**0.5)*((S_w)**0.622)*(A**0.785)*tc_r*((1+tp_r)**0.05)*((math.cos(swp))**-1.0)*((S_csw)**0.04);

# #weight for horizontal tail
# F_w=8.0380      #fuselage width at horizontal tail intersection,ft
# B_h=24.689        #horizontal tail span,ft
# S_ht=184.719467   #horizontal tail area,ft square
# W_ht=3.316*((1+F_w/B_h)**-2)*((W_dg*N_z*0.001)**0.260)*(S_ht**0.806)

# #weight for vertical tail
# K_rht=1.047      #for all moving tail from book
# H_t=0.328084      #horizontal tail height above fuselage,ft
# H_v=0.492126      #vertical tail height above fuselage,ft
# S_vt=118.72593 #vertical tail area,ft square(for both tails)
M=2.2            #design max mach number
# L_t=22.5     #tail length, wing MAC to tail MAC,
# S_r=95.002273       #rudder area,ft square           
# A_vt=1.2         #AR of vertical tail
# tp_r_vt=0.3      #taper ratio of vertical tail
# swp_vt=0.6705555    #quarter chord sweep of vertical tail in radian
# W_vt=0.452*K_rht*((1+H_t/H_v)**0.5)*((W_dg*N_z)**0.488)*(S_vt**0.718)*(M**0.341)*(L_t**-1.0)*((1+S_r/S_vt)**0.348)*(A_vt**0.223)*((1+tp_r_vt)**0.25)*((math.cos(swp_vt))**-0.323)

#weight for fuselage
K_dwf=1         #from book
L= 50     #fuselage structural length,ft
D=7.7985564       #fuselage structural depth,ft
W=8.39895       #total fuselage structural width,ft
#fudge factor taken as 1.3
W_f=1.3*(0.499*K_dwf*(W_dg**0.35)*(N_z**0.25)*(L**0.5)*(D**0.849)*(W**0.685)) 

# #weight for main landing gear
K_cb=1          #from book
K_tpg=0.826     #for tripod from book
W_l=30845.97741    #landing design gross weight,lb
N_l=8.25        #ultimate landing load factor,Ngear*1.5
L_m=148         #extended length of main landing gear,in
#fudge factor taken as 1.3
W_mlg=1.3*(K_cb*K_tpg*((W_l*N_l)**0.25)*(L_m**0.973))

# #weight for nose landing gear
L_n=138         #extended nose gear length,in
N_nw=2          #number of nose wheels
#fudge factor taken as 1.3
W_nlg=1.3*(((W_l*N_l)**0.290)*(L_n**0.5)*(N_nw**0.525))

#weight for engine mounts
N_en=2          #number of engines
T=65000  #total engine thrust,lb
W_em=0.013*(N_en**0.795)*(T**0.579)*N_z

#weight for firewall
S_fw=23.6      #firewall surface area,ft square,surface area at max engine dia*2
W_fw=1.13*S_fw

#weight for engine section
W_en=4100   #engine weight ,each,lb
W_ens=0.01*(W_en**0.717)*N_en*N_z

#weight for air induction system
K_vg=1          #const geo, from reference AC
L_d=15.367454    #duct length,ft
K_d=1.31        #duct constant
L_s=7.683727    #single duct length,ft
D_e=3.875      #engine diameter,ft
W_ais=13.29*K_vg*(L_d**0.643)*(K_d**0.182)*(N_en**1.498)*((L_s/L_d)**-0.373)*(D_e)

#weight for tailpipe
L_tp= 7.5   #length of tailpipe,ft,superhornet, distance from turbine exit to nozzle exit
W_tp=3.5*D_e*L_tp*N_en

#weight for engine cooling
L_sh=5         #length of engine cooling shroud,ft,superhornet F414-class, 
W_engc=4.55*D_e*L_sh*N_en

#weight for oil cooling
W_oc=37.82*(N_en**1.023)

#Weight for engine controls
L_ec=34  #routing distance from engine front to cockpit(total for dual engine),ft            
W_engctrl=10.5*(N_en**1.008)*(L_ec**0.222)

#weight for starter,pneumatic
T_e=32500    #thrust per engine.lb
W_pn=0.025*(T_e**0.760)*(N_en**0.72)

#weight for fuel system and tanks
V_t=5570   #total fuel volume,gal, Weight of fuel/density of JP-8
V_i=2228   #integral tanks volume,gal,0.4*V_t 
V_p=3342   #self sealing protected tanks volume,gal,0.6*V_t
N_t=3       #no. of fuel tanks, left wing, right wing,fuselage 
SFC=1.94    #engine specific fuel consumption at maximum thrust, lb/hr/lb
W_fsat=7.45*(V_t**0.47)*((1+V_i/V_t)**-0.095)*(1+V_p/V_t)*(N_t**0.066)*(N_en**0.052)*((0.001*T*SFC)**0.249)

#weight for flight controls
S_cs=352.395282   #total area of control surface,ft square
N_s=4           #number of flight control systems,taken from superhornet
N_c=2           #number of crew
W_f_ctrl=36.28*(M**0.003)*(S_cs**0.489)*(N_s**0.484)*(N_c**0.127)


#weight for instruments
N_t=3           #number of fuel tanks,taken all internal
N_ci=1.2        #pilot plus backseater
W_ins=8.0+(36.37*(N_en**0.676)*(N_t**0.237))+(26.4*((1+N_ci)**1.356))

#weight for hydraulics
K_vsh=1         #from book
N_u=12          #number of hydraulic utility functions(5-15), superhornet
W_hyd=37.32*K_vsh*(N_u**0.664)

#weight for electrical 
K_mc=1          #1.45 if mission completion required after failure; = 1.0 otherwise
R_kva=150       #system electrical rating, kV · A (typically 40-60 for transports, 110-160 for fighters and bombers) 
L_a= 35       #electrical routing distance, generators to avionics to cockpit, ft
N_gen=2         #no. of generators typically equal to no. of engines
W_elec=172.2*K_mc*(R_kva**0.152)*(N_c**0.10)*(L_a**0.10)*(N_gen**0.091)

#weight for avionics
W_uav=1241.29      #uninstalled avionics weight, lb (typically = 800-1400 lb)
W_avi=2.117*(W_uav**0.933)

#weight for furnishings
W_fur=217.6*N_c

#weight for air conditioning and anti-ice 
W_ac_ai=201.6*(((W_uav+(200*N_c))*0.001)**0.735)

#weight for handling gear
W_hg=0.00032*W_dg


# --- PRINTING RESULTS ---
print("="*40)
print(f"{'COMPONENT':<25} | {'WEIGHT (lb)':>10}")
print("-" * 40)

# Structural Group
# print(f"{'Wing':<25} | {W_wing:>10.2f}")
# print(f"{'Horizontal Tail':<25} | {W_ht:>10.2f}")
# print(f"{'Vertical Tail':<25} | {W_vt:>10.2f}")
print(f"{'Fuselage':<25} | {W_f:>10.2f}")
print(f"{'Main landing gear':<25} | {W_mlg:>10.2f}")
print(f"{'Nose landing gear':<25} | {W_nlg:>10.2f}")
print(f"{'Firewall':<25} | {W_fw:>10.2f}")
print(f"{'Engine Mounts':<25} | {W_em:>10.2f}")
print(f"{'Engine Section':<25} | {W_ens:>10.2f}")
print(f"{'Air Induction System':<25} | {W_ais:>10.2f}")

# Propulsion Group
print(f"{'Starter (engine cooling)':<25} | {W_engc:>10.2f}")
print(f"{'Starter (tailpipe)':<25} | {W_tp:>10.2f}")
print(f"{'Oil Cooling':<25} | {W_oc:>10.2f}")
print(f"{'Engine Controls':<25} | {W_engctrl:>10.2f}")
print(f"{'Starter (Pneumatic)':<25} | {W_pn:>10.2f}")
print(f"{'Starter (fuel system and tanks)':<25} | {W_fsat:>10.2f}")

# Systems Group
print(f"{'Flight Controls':<25} | {W_f_ctrl:>10.2f}")
print(f"{'Instruments':<25} | {W_ins:>10.2f}")
print(f"{'Hydraulics':<25} | {W_hyd:>10.2f}")
print(f"{'Electrical':<25} | {W_elec:>10.2f}")
print(f"{'Avionics':<25} | {W_avi:>10.2f}")
print(f"{'Furnishings':<25} | {W_fur:>10.2f}")
print(f"{'Air Cond / Anti-Ice':<25} | {W_ac_ai:>10.2f}")
print(f"{'Handling Gear':<25} | {W_hg:>10.2f}")

print("-" * 40)

# Calculate the sum of the active components
total_we =  W_f + W_mlg + W_nlg + W_fw + W_em + W_ens + W_ais + W_engc + W_tp + W_oc + W_engctrl + W_pn + W_fsat + W_f_ctrl + W_ins + W_hyd + W_elec + W_avi + W_fur + W_ac_ai + W_hg

print(f"{'TOTAL PARTIAL EMPTY WEIGHT':<25} | {total_we:>10.2f} lb")
print("="*40)


