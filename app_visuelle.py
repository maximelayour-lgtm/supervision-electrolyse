import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# ==========================================
# CONSTANTES DU PROCÉDÉ [cite: 5, 6, 7, 8]
# ==========================================
F = 96485                
M_HCL = 36.46            
M_CL2 = 71.0             
N_CELLULES = 108         
CONC_HCL = 0.35          
DENSITE_HCL = 1.17       
RENDEMENT_ANO = 0.98     
U0_APPROX = 310.0        

MAX_PERTE_CE_PAR_MOIS = -0.15 
MAX_HAUSSE_R_PAR_MOIS = 0.005
SEUIL_CE_CRITIQUE = 93

st.set_page_config(page_title="Suivi Électrolyse", layout="wide")
st.title("📊 Tableau de Bord : Suivi des Électrolyseurs")

def calculer_rendement(row):
    # Basé sur la loi de Faraday et la stœchiométrie [cite: 3]
    I_A = row['I_kA'] * 1000
    
    # PROTECTION DIVISION PAR ZÉRO : Si arrêt usine, on renvoie une valeur vide
    if I_A <= 0:
        return np.nan

    if row['QHCl_L_h'] > 0:
        masse_pure_hcl = row['QHCl_L_h'] * DENSITE_HCL * CONC_HCL
        destr_oh_kmol_h = masse_pure_hcl / M_HCL
    else:
        # Estimation via équation : 2 Cl- donnent Cl2 + 2 électrons [cite: 13]
        prod_cl2_kg = (I_A * M_CL2 * 3600 * RENDEMENT_ANO * N_CELLULES) / (2 * F * 1000)
        moles_cl2 = prod_cl2_kg / M_CL2
        pct_o2 = row['%O2_Mesure']
        moles_o2 = moles_cl2 * (pct_o2 / (100 - pct_o2)) if pct_o2 < 100 else 0
        destr_oh_kmol_h = moles_o2 * 4 # 4 OH- donnent O2 + 2 H2O + 4 e- [cite: 18]

    perte_ce_fraction = (destr_oh_kmol_h / 3.6) * F / (I_A * N_CELLULES)
    return (1 - perte_ce_fraction) * 100

# ==========================================
# GESTION DES DONNÉES (MENU LATÉRAL)
# ==========================================
st.sidebar.header("📂 Chargement des données")

# 1. Zone d'upload toujours visible (Prioritaire)
fichier_upload = st.sidebar.file_uploader("1. Chargez votre propre CSV", type=["csv"])

st.sidebar.markdown("---")
st.sidebar.markdown("**OU**")

# 2. Menu déroulant pour les exemples
exemple_choisi = st.sidebar.selectbox(
    "2. Utilisez un fichier d'exemple :",
    ("Aucun",
     "01 - Début de vie (CE ~96%)",
     "02 - Milieu de vie (CE ~93%)",
     "03 - Fin de vie (CE ~87%)",
     "04 - Panne soudaine",
     "05 - Année complète avec arrêts")
)

df = None

# --- LOGIQUE DE PRIORITÉ ---
if fichier_upload is not None:
    # Si un fichier est uploadé, on l'utilise
    df = pd.read_csv(fichier_upload, sep=';', decimal=',')
    st.sidebar.success("Fichier personnel chargé avec succès !")

elif exemple_choisi != "Aucun":
    # Sinon, si un exemple est sélectionné, on utilise l'exemple
    fichiers_exemples = {
        "01 - Début de vie (CE ~96%)": "01_debut_vie.csv",
        "02 - Milieu de vie (CE ~93%)": "02_milieu_vie.csv",
        "03 - Fin de vie (CE ~87%)": "03_fin_vie.csv",
        "04 - Panne soudaine": "04_panne_soudaine.csv",
        "05 - Année complète avec arrêts": "05_annee_complete_incidents.csv"
    }
    
    fichier_a_charger = fichiers_exemples[exemple_choisi]
    
    try:
        df = pd.read_csv(fichier_a_charger, sep=';', decimal=',')
        st.sidebar.info(f"Données d'exemple activées : {exemple_choisi}")
    except FileNotFoundError:
        st.sidebar.error(f"Fichier d'exemple introuvable. N'oubliez pas de l'uploader sur GitHub !")

# ==========================================
# SUITE DU CODE (Analyse et Affichage)
# ==========================================
if df is not None:
    df['Date'] = pd.to_datetime(df['Date'])
    # ... (La suite des calculs CE, Résistance et graphiques reste exactement la même)
    
    df['CE_Calcule'] = df.apply(calculer_rendement, axis=1)
    df['Resistance'] = np.where(df['I_kA'] > 0, (df['U_V'] - U0_APPROX) / df['I_kA'], np.nan)
    
    # --- ANALYSE DES TENDANCES (SUR LE DERNIER MOIS UNIQUEMENT) ---
    resultats = []
    for nom, groupe in df.groupby('Electrolyseur'):
        groupe = groupe.sort_values('Date')
        
        # On retire les jours d'arrêt
        groupe_propre = groupe.dropna(subset=['CE_Calcule', 'Resistance']).copy()
        
        if len(groupe_propre) == 0:
            continue
            
        # 1. ISOLER LE DERNIER MOIS
        date_max = groupe_propre['Date'].max()
        date_limite = date_max - pd.Timedelta(days=30)
        groupe_recent = groupe_propre[groupe_propre['Date'] >= date_limite].copy()
        
       if len(groupe_recent) < 3:
            resultats.append({
                'Électro.': nom,
                'CE Actuel (%)': "N/A",
                'Δ CE/mois': "N/A",
                'Δ R/mois': "N/A",
                'Membrane': "Pas assez de données",
                'Revêtement': "Pas assez de données"
            })
            continue
            
        # 2. CALCULS DES PENTES UNIQUEMENT SUR LA FENÊTRE RÉCENTE
        jours_ecoules = (groupe_recent['Date'] - groupe_recent['Date'].min()).dt.days
            
        pente_ce_jour, _ = np.polyfit(jours_ecoules, groupe_recent['CE_Calcule'], 1)
        pente_r_jour, _ = np.polyfit(jours_ecoules, groupe_recent['Resistance'], 1)
        
        pente_ce_mois = pente_ce_jour * 30
        pente_r_mois = pente_r_jour * 30
        
        ce_moyen_recent = groupe_recent['CE_Calcule'].tail(5).mean() 
        
        # 3. DIAGNOSTICS
        if ce_moyen_recent < SEUIL_CE_CRITIQUE:
            diag_mem = "🔴 FIN DE VIE (<90%)"
        elif pente_ce_mois < MAX_PERTE_CE_PAR_MOIS:
            diag_mem = "⚠️ CHUTE RAPIDE"
        else:
            diag_mem = "✅ Normal"
            
        diag_rev = "⚠️ ACCÉLÉRÉ" if pente_r_mois > MAX_HAUSSE_R_PAR_MOIS else "✅ Normal"

        resultats.append({
            'Électro.': nom,
            'CE Actuel (%)': f"{ce_moyen_recent:.1f}",
            'Δ CE/mois': f"{pente_ce_mois:+.3f} %",
            'Δ R/mois': f"{pente_r_mois:+.4f} Ω",
            'Membrane': diag_mem,
            'Revêtement': diag_rev
        })
            continue
            
        # 2. CALCULS DES PENTES UNIQUEMENT SUR LA FENÊTRE RÉCENTE
        jours_ecoules = (groupe_recent['Date'] - groupe_recent['Date'].min()).dt.days
            
        pente_ce_jour, _ = np.polyfit(jours_ecoules, groupe_recent['CE_Calcule'], 1)
        pente_r_jour, _ = np.polyfit(jours_ecoules, groupe_recent['Resistance'], 1)
        
        pente_ce_mois = pente_ce_jour * 30
        pente_r_mois = pente_r_jour * 30
        
        ce_moyen_recent = groupe_recent['CE_Calcule'].tail(5).mean() 
        
        # 3. DIAGNOSTICS
        if ce_moyen_recent < SEUIL_CE_CRITIQUE:
            diag_mem = "🔴 FIN DE VIE (<93%)"
        elif pente_ce_mois < MAX_PERTE_CE_PAR_MOIS:
            diag_mem = "⚠️ Dégradation potentielle membranes"
        else:
            diag_mem = "✅ Normal"
            
        diag_rev = "⚠️ Usure prématurée" if pente_r_mois > MAX_HAUSSE_R_PAR_MOIS else "✅ Normal"

        resultats.append({
            'Électro.': nom,
            'CE Actuel (%)': f"{ce_moyen_recent:.1f}",
            'Δ CE/mois': f"{pente_ce_mois:+.3f} %",
            'Δ R/mois': f"{pente_r_mois:+.4f} Ω",
            'Membrane': diag_mem,
            'Revêtement': diag_rev
        })

    # --- AFFICHAGE DE L'INTERFACE ---
    st.subheader("📋 Bilan de santé des électrolyseurs (Sur les 30 derniers jours de production)")
    df_res = pd.DataFrame(resultats)
    st.dataframe(df_res, use_container_width=True)
    
    st.markdown("---")
    
    st.subheader("📈 Visualisation des Performances (Historique Complet)")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Évolution du Rendement Cathodique (CE)**")
        fig_ce = px.line(df, x='Date', y='CE_Calcule', color='Electrolyseur')
        fig_ce.add_hline(y=SEUIL_CE_CRITIQUE, line_dash="dash", line_color="red", annotation_text="Seuil Critique")
        fig_ce.update_traces(connectgaps=False)
        st.plotly_chart(fig_ce, use_container_width=True)
        
    with col2:
        st.markdown("**Évolution de la Résistance (État des Revêtements)**")
        fig_r = px.line(df, x='Date', y='Resistance', color='Electrolyseur')
        fig_r.update_traces(connectgaps=False)
        st.plotly_chart(fig_r, use_container_width=True)

else:
    st.info("En attente d'un fichier CSV pour afficher le tableau de bord.")
