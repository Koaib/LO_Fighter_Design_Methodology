%% run_rcs.m
% Automated POFACETS Monostatic RCS Pipeline
% Settings: Theta=90 (fixed), Phi=0:1:360, Freq=12GHz, Phi-pol (TE-z)
% Saves results to Results/RCS/

clear; clc; close all;

% =========================
% PATH SETUP
% =========================

SCRIPT_DIR = fileparts(mfilename('fullpath'));
ROOT_DIR   = fullfile(SCRIPT_DIR, '..');

MAIN_DIR   = ROOT_DIR;
POFACETS   = fullfile(MAIN_DIR, 'POFACETS', 'pofacets4.5', 'pofacets4.5');
STL_DIR    = fullfile(MAIN_DIR, 'STL_Files');
RESULTS    = fullfile(MAIN_DIR, 'Results', 'RCS');

addpath(POFACETS);
if ~exist(RESULTS, 'dir'), mkdir(RESULTS); end

STL_FILE   = fullfile(STL_DIR, 'aircraft.stl');
MAT_FILE   = fullfile(RESULTS, 'aircraft_model.mat');

% =========================
% STEP 1: IMPORT STL → .MAT
% (replicates utilities.m ImportSTL_Callback)
% =========================

fprintf('Importing STL: %s\n', STL_FILE);

fid = fopen(STL_FILE);
if fid == -1
    error('Cannot open STL file: %s', STL_FILE);
end

modelname = fgetl(fid);   % first line is solid name
fprintf('Model name from STL: %s\n', modelname);

lnn=0; nv=0; nod=0; ntri=1; scale=1;
X=[]; Y=[]; Z=[]; Nv_arr=[];

while ~feof(fid)
    sin_line = fgetl(fid);
    lnn = lnn + 1;
    S = strfind(sin_line, 'vertex');
    if ~isempty(S)
        K = strrep(sin_line, 'vertex', ' ');
        nv  = nv + 1;
        nod = nod + 1;
        B = sscanf(K, '%f');
        A(nv,:) = B';
        x_arr(ntri, nod) = B(1);
        y_arr(ntri, nod) = B(2);
        z_arr(ntri, nod) = B(3);
        Nv_arr(ntri, nod) = nv;
    end
    if nod == 3, nod = 0; ntri = ntri + 1; end
end
fclose(fid);

% Remove duplicate nodes
[V, ~, indexn] = unique(A, 'rows');
F = indexn(Nv_arr);

coord    = V;
facet    = F;
facet(:,4) = 1;   % illumination: front face only
facet(:,5) = 0;   % surface resistivity: PEC
scale      = 1;
symplanes  = [0 0 0];

for i = 1:size(facet,1)
    comments{i,1}  = 'Model Surface';
    matrl{i,1}     = 'PEC';
    matrl{i,2}     = [0 0 0 0 0];
end

save(MAT_FILE, 'coord','facet','scale','symplanes','comments','matrl');
fprintf('Model saved to: %s\n', MAT_FILE);

% =========================
% STEP 2: MONOSTATIC RCS
% (replicates CalcMono.m logic directly)
% Settings from GUI screenshot:
%   Theta: start=90, stop=90 (fixed → phi-cut)
%   Phi:   start=0,  stop=360, increment=1
%   Freq:  12 GHz
%   Pol:   Phi (TE-z) → Et=0, Ep=1
%   Lt=1e-5, Nt=5
% =========================

fprintf('Running monostatic RCS...\n');

C      = 3e8;
freq   = 12;           % GHz
wave   = C / (freq * 1e9);
bk     = 2*pi / wave;
rad    = pi/180;

% Angle settings
tstart = 90; tstop  = 90; delt = 1;
pstart = 0;  pstop  = 360; delp = 1;

% Taylor series
Lt = 1e-5;  Nt = 5;

% Surface roughness (none)
corr  = 0;   corel = corr/wave;
std_v = 0;   delsq = std_v^2;
cfac1 = exp(-4*bk^2*delsq);
cfac2 = 4*pi*(bk*corel)^2*delsq;

% Polarization: Phi (TE-z) → Et=0, Ep=1
Et = 0+1j*0;
Ep = 1+1j*0;

% Prepare facet data
nvert = size(coord,1);
ntria = size(facet,1);
xpts  = coord(:,1); ypts = coord(:,2); zpts = coord(:,3);
node1 = facet(:,1); node2 = facet(:,2); node3 = facet(:,3);
ilum  = facet(:,4); Rs    = facet(:,5);
iflag = 0;

for i = 1:ntria
    vind(i,:) = [node1(i) node2(i) node3(i)];
end
x = xpts; y = ypts; z = zpts;
for i = 1:nvert
    r(i,:) = [x(i) y(i) z(i)];
end

% Normals and areas
for i = 1:ntria
    Av = r(vind(i,2),:) - r(vind(i,1),:);
    Bv = r(vind(i,3),:) - r(vind(i,2),:);
    Cv = r(vind(i,1),:) - r(vind(i,3),:);
    N_vec(i,:) = -cross(Bv, Av);
    d1 = norm(Av); d2 = norm(Bv); d3 = norm(Cv);
    ss = 0.5*(d1+d2+d3);
    Area(i) = sqrt(max(ss*(ss-d1)*(ss-d2)*(ss-d3), 0));
    Nn = norm(N_vec(i,:));
    if Nn > 0, N_vec(i,:) = N_vec(i,:)/Nn; end
    beta_arr(i)  = acos(max(-1, min(1, N_vec(i,3))));
    alpha_arr(i) = atan2(N_vec(i,2), N_vec(i,1));
end

% Angle loop
it = floor((tstop-tstart)/delt) + 1;
ip = floor((pstop-pstart)/delp) + 1;

Sth = zeros(ip, it);
Sph = zeros(ip, it);

for i1 = 1:ip
    for i2 = 1:it
        phi_deg(i1,i2)   = pstart + (i1-1)*delp;
        theta_deg(i1,i2) = tstart + (i2-1)*delt;
        phr = phi_deg(i1,i2) * rad;
        thr = theta_deg(i1,i2) * rad;

        st = sin(thr); ct = cos(thr);
        cp = cos(phr); sp = sin(phr);
        u = st*cp; v = st*sp; w = ct;
        uu = ct*cp; vv = ct*sp; ww = -st;

        e0_vec(1) = uu*Et - sp*Ep;
        e0_vec(2) = vv*Et + cp*Ep;
        e0_vec(3) = ww*Et;

        sumt = 0; sump = 0; sumdt = 0; sumdp = 0;

        for m = 1:ntria
            alpha = alpha_arr(m); beta = beta_arr(m);
            [Ets, Etd, Eps, Epd] = facetRCS(thr, phr, thr, phr, ...
                N_vec(m,:), ilum(m), iflag, alpha, beta, Rs(m), Area(m), ...
                x, y, z, vind(m,:), e0_vec, Nt, Lt, cfac2, corel, wave, ...
                0, 0, 0, 1, 0, 0);
            sumt  = sumt  + Ets;
            sump  = sump  + Eps;
            sumdt = sumdt + abs(Etd);
            sumdp = sumdp + abs(Epd);
        end

        Sth(i1,i2) = 10*log10(4*pi*cfac1*(abs(sumt)^2 + sqrt(1-cfac1^2)*sumdt)/wave^2 + 1e-10);
        Sph(i1,i2) = 10*log10(4*pi*cfac1*(abs(sump)^2 + sqrt(1-cfac1^2)*sumdp)/wave^2 + 1e-10);
    end
end

RCSth = Sth; RCSph = Sph;
fprintf('RCS computation complete.\n');

% =========================
% STEP 3: SAVE RESULTS
% =========================

theta = theta_deg;
phi   = phi_deg;

% Save .mat results
save(fullfile(RESULTS, 'rcs_results.mat'), 'theta','phi','freq','Sth','Sph');
fprintf('Results saved: rcs_results.mat\n');

% Save .txt results
fid_out = fopen(fullfile(RESULTS, 'rcs_results.txt'), 'w');
fprintf(fid_out, 'Monostatic RCS Results\n');
fprintf(fid_out, 'Frequency: %.1f GHz | Theta: %.1f deg (fixed) | Phi: %.1f to %.1f deg\n', ...
    freq, tstart, pstart, pstop);
fprintf(fid_out, 'Polarization: Phi (TE-z)\n\n');
fprintf(fid_out, '%-12s %-12s %-14s %-14s\n', 'Theta(deg)', 'Phi(deg)', 'RCS_Theta(dBsm)', 'RCS_Phi(dBsm)');
fprintf(fid_out, '%s\n', repmat('-',1,56));
for i1 = 1:ip
    for i2 = 1:it
        fprintf(fid_out, '%-12.1f %-12.1f %-14.4f %-14.4f\n', ...
            theta_deg(i1,i2), phi_deg(i1,i2), Sth(i1,i2), Sph(i1,i2));
    end
end
fclose(fid_out);
fprintf('Results saved: rcs_results.txt\n');

% =========================
% STEP 4: LINEAR PLOT + SAVE
% =========================

Smax = max([max(max(Sth)), max(max(Sph))]);
Lmax = (floor(Smax/5)+1)*5;
Lmin = Lmax - 60;

fig1 = figure('Name','Monostatic RCS - Linear','Visible','on');
plot(phi_deg(:,1), Sth(:,1), 'b', phi_deg(:,1), Sph(:,1), 'r', 'LineWidth',1);
grid on;
xlabel('\phi (deg)');
ylabel('RCS (dBsm)');
title(sprintf('Monostatic RCS | \\theta=%.0f° | f=%.0f GHz | Blue:\\theta-pol  Red:\\phi-pol', tstart, freq));
legend('RCS \theta-pol','RCS \phi-pol');
xlim([pstart pstop]); ylim([Lmin Lmax]);
saveas(fig1, fullfile(RESULTS, 'rcs_linear.png'));
fprintf('Figure saved: rcs_linear.png\n');

% =========================
% STEP 5: POLAR PLOT + SAVE
% =========================

dynr   = 60;
ang    = phi_deg(:,1);
sth_v  = Sth(:,1);
sph_v  = Sph(:,1);

% Clamp to dynamic range
pmax  = max([max(sth_v), max(sph_v)]);
top   = (floor(pmax/5)+1)*5;
sth_v = max(sth_v, top-dynr);
sph_v = max(sph_v, top-dynr);
rhoth = sth_v + dynr - top;
rhoph = sph_v + dynr - top;

fig2 = figure('Name','Monostatic RCS - Polar','Visible','on');
hold on; axis off; axis equal;

% Draw rings
rticks = 6;
dbstep = dynr/rticks;
th_circle = linspace(0, 2*pi, 200);
for i = 1:rticks
    r_ring = i*(dynr/rticks);
    plot(r_ring*cos(th_circle), r_ring*sin(th_circle), '-', 'Color',[0.6 0.6 0.6], 'LineWidth',0.5);
    text(0, r_ring+0.5, sprintf('%.0f', r_ring-dynr+top), 'FontSize',7, 'HorizontalAlignment','center');
end

% Draw spokes
for a_sp = 0:30:330
    plot([0, dynr*cos(a_sp*rad)], [0, dynr*sin(a_sp*rad)], '-', 'Color',[0.7 0.7 0.7], 'LineWidth',0.5);
    text(1.12*dynr*cos(a_sp*rad), 1.12*dynr*sin(a_sp*rad), sprintf('%d°',a_sp), ...
        'FontSize',7,'HorizontalAlignment','center');
end

% Plot RCS
ang_rad = ang * rad;
plot(rhoth.*cos(ang_rad), rhoth.*sin(ang_rad), 'b', 'LineWidth',1);
plot(rhoph.*cos(ang_rad), rhoph.*sin(ang_rad), 'r', 'LineWidth',1.5);
legend('RCS \theta-pol','RCS \phi-pol','Location','SouthEast');
title(sprintf('Polar RCS | \\theta=%.0f° | f=%.0f GHz', tstart, freq));

saveas(fig2, fullfile(RESULTS, 'rcs_polar.png'));
fprintf('Figure saved: rcs_polar.png\n');

% =========================
% STEP 6: 3D DISPLAY + SAVE
% =========================

fig3 = figure('Name','3D RCS Display','Visible','on');

% Plot faceted model
node1=facet(:,1); node2=facet(:,2); node3=facet(:,3);
hold on;
for i = 1:ntria
    X3 = [x(vind(i,1)) x(vind(i,2)) x(vind(i,3)) x(vind(i,1))];
    Y3 = [y(vind(i,1)) y(vind(i,2)) y(vind(i,3)) y(vind(i,1))];
    Z3 = [z(vind(i,1)) z(vind(i,2)) z(vind(i,3)) z(vind(i,1))];
    plot3(X3, Y3, Z3, 'b', 'LineWidth', 0.3);
end

% Overlay RCS as 3D polar (matching POFACETS CalcMono show3D logic)
Sth1 = max(Sth(:,1), Lmax-60);
Sph1 = max(Sph(:,1), Lmax-60);
m0   = 2*max(max(abs(coord)));
MinRCS = min([min(Sth1); min(Sph1)]);
Sth1 = Sth1 - MinRCS;  Sph1 = Sph1 - MinRCS;
MaxRCS = max([max(Sth1); max(Sph1)]);
if MaxRCS > 0
    Sth1 = m0*Sth1/MaxRCS;
    Sph1 = m0*Sph1/MaxRCS;
end
th_fixed = tstart * rad;
ph_arr   = phi_deg(:,1) * rad;
xth = Sth1 .* sin(th_fixed) .* cos(ph_arr);
yth = Sth1 .* sin(th_fixed) .* sin(ph_arr);
zth = Sth1 .* cos(th_fixed) .* ones(size(ph_arr));
xph = Sph1 .* sin(th_fixed) .* cos(ph_arr);
yph = Sph1 .* sin(th_fixed) .* sin(ph_arr);
zph = Sph1 .* cos(th_fixed) .* ones(size(ph_arr));

plot3(xth, yth, zth, 'r', 'LineWidth', 1.5);
plot3(xph, yph, zph, 'g', 'LineWidth', 1.5);
axis equal; grid on;
xlabel('X'); ylabel('Y'); zlabel('Z');
title(sprintf('3D RCS | RED: \\theta-pol  GREEN: \\phi-pol | f=%.0f GHz', freq));
view(45, 30);

saveas(fig3, fullfile(RESULTS, 'rcs_3d.png'));
fprintf('Figure saved: rcs_3d.png\n');

fprintf('\n✅ All done. Results in: %s\n', RESULTS);