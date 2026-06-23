import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# ==========================================
# CONSTANTES DU PROCÉDÉ
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
SEUIL_CE_CRITIQUE = 90.0 

st.set_page_config(page_title="Suivi Électrolyse", layout="wide")
st.title("📊 Tableau de Bord : Suivi des Électrolyseurs")

def calculer_rendement(row):
    I_A = row['I_kA'] * 1000
    
    if I_A <= 0:
        return np.nan

    if row['QHCl_L_h'] > 0:
        masse_pure_hcl = row['QHCl_L_h'] * DENSITE_HCL * CONC_HCL
        destr_oh_kmol_h = masse_pure_hcl / M_HCL
    else:
        prod_cl2_kg = (I_A * M_CL2 * 3600 * RENDEMENT_ANO * N_CELLULES) / (2 * F * 1000)
        moles_cl2 = prod_cl2_kg / M_CL2
        pct_o2 = row['%O2_Mesure']
        moles_o2 = moles_cl2 * (pct_o2 / (100 - pct_o2)) if pct_o2 < 100 else 0
        destr_oh_kmol_h = moles_o2 * 4

    perte_ce_fraction = (destr_oh_kmol_h / 3.6) * F / (I_A * N_CELLULES)
    return (1 - perte_ce_fraction) * 100

# ==========================================
# GESTION DES DONNÉES (MENU LATÉRAL)
# ==========================================
st.sidebar.header("📂 Chargement des données")

fichier_upload = st.sidebar.file_uploader("1. Chargez votre propre CSV", type=["csv"])

st.sidebar.markdown("---")
st.sidebar.markdown("**OU**")

exemple_choisi = st.sidebar.selectbox(
    "2. Utilisez un fichier d'exemple :",
    ("Aucun",
     "01 - Début de vie (CE ~96%)",
     "02 - Milieu de vie (CE ~93%)",
     "03 - Fin de vie (CE ~87%)",
     "04 - Panne soudaine",
     "05 - Année complète avec arrêts")
)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Paramètres d'analyse")
tolerance_hcl = st.sidebar.slider("Tolérance Écart HCl (%)", min_value=3, max_value=8, value=5, step=1)

df = None

if fichier_upload is not None:
    df = pd.read_csv(fichier_upload, sep=';', decimal=',')
    st.sidebar.success("Fichier personnel chargé avec succès !")

elif exemple_choisi != "Aucun":
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
        st.sidebar.error("Fichier d'exemple introuvable. N'oubliez pas de l'uploader sur GitHub !")

# ==========================================
# ANALYSE ET AFFICHAGE
# ==========================================
if df is not None:
    df['Date'] = pd.to_datetime(df['Date'])
    
    df['CE_Calcule'] = df.apply(calculer_rendement, axis=1)
    df['Resistance'] = np.where(df['I_kA'] > 0, (df['U_V'] - U0_APPROX) / df['I_kA'], np.nan)
    
    resultats = []
    for nom, groupe in df.groupby('Electrolyseur'):
        groupe = groupe.sort_values('Date')
        
        groupe_propre = groupe.dropna(subset=['CE_Calcule', 'Resistance']).copy()
        
        if len(groupe_propre) == 0:
            continue
            
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
                'Revêtement': "Pas assez de données",
                'Injection HCl': "N/A"
            })
            continue
            
        jours_ecoules = (groupe_recent['Date'] - groupe_recent['Date'].min()).dt.days
            
        pente_ce_jour, _ = np.polyfit(jours_ecoules, groupe_recent['CE_Calcule'], 1)
        pente_r_jour, _ = np.polyfit(jours_ecoules, groupe_recent['Resistance'], 1)
        
        pente_ce_mois = pente_ce_jour * 30
        pente_r_mois = pente_r_jour * 30
        
        ce_moyen_recent = groupe_recent['CE_Calcule'].tail(5).mean() 
        
        # ==========================================
        # ALERTE DE COHÉRENCE HCl
        # ==========================================
        derniere_ligne = groupe_recent.iloc[-1]
        I_actuel_kA = derniere_ligne['I_kA']
        Q_HCl_mesure = derniere_ligne['QHCl_L_h']
        
        diag_coherence = "✅ Cohérent"
        
        if I_actuel_kA > 0:
            I_A = I_actuel_kA * 1000
            perte_rendement = 1 - (ce_moyen_recent / 100)
            destr_oh_kmol_h = (I_A * N_CELLULES * perte_rendement / F) * 3.6
            masse_pure_hcl = destr_oh_kmol_h * M_HCL
            q_hcl_theorique = (masse_pure_hcl / CONC_HCL) / DENSITE_HCL
            
            if q_hcl_theorique > 0:
                ecart_pct = ((Q_HCl_mesure - q_hcl_theorique) / q_hcl_theorique) * 100
                
                if ecart_pct <= -tolerance_hcl:
                    diag_coherence = f"⚠️ Trop faible ({ecart_pct:.0f}%)"
                elif ecart_pct >= tolerance_hcl:
                    diag_coherence = f"⚠️ Anormalement fort (+{ecart_pct:.0f}%)"
        else:
            diag_coherence = "Arrêt usine"
            
        # ==========================================
        # DIAGNOSTICS FINAUX
        # ==========================================
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
            'Revêtement': diag_rev,
            'Injection HCl': diag_coherence
        })

    # ==========================================
    # AFFICHAGE DE L'INTERFACE
    # ==========================================
    st.subheader("📋 Bilan de Santé (Sur les 30 derniers jours de production)")
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
    st.info("En attente de sélection ou de chargement d'un fichier CSV...")
