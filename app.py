# app.py

import pandas as pd
import plotly.express as px
from flask import Flask, render_template, request, redirect, url_for, session
import os
import io

# --- Configuración de la Aplicación ---
app = Flask(__name__)
# Configuración esencial para usar la sesión (session)
app.secret_key = 'tu_clave_secreta_aqui_para_seguridad_final' 

# --- Funciones Auxiliares ---

def identificar_columnas_tareas(df):
    """Filtra y devuelve los nombres de las columnas que representan actividades o tareas (para /resultados)."""
    columnas_identificacion = ['cedula', 'nombre', 'curso']
    return [
        col for col in df.columns 
        if isinstance(col, str) and col.lower().strip() not in columnas_identificacion
    ]

def identificar_columnas_evaluaciones(df):
    """Intenta identificar columnas de subtemas para /evaluaciones (basado en Px o similar)."""
    # Se asume que las columnas de subtemas de evaluación (ej. P1, P2) no tienen decimales (son 0 o 1)
    columnas_identificacion = ['cedula', 'nombre', 'curso']
    cols_a_excluir = [col for col in df.columns if isinstance(col, str) and col.lower().strip() in columnas_identificacion]
    
    subtemas = []
    
    # Intentar identificar la columna de nota final (normalmente la última columna que no es Cédula/Nombre/Curso)
    # y excluirla de los subtemas.
    otras_cols = [col for col in df.columns if col not in cols_a_excluir]
    
    # Suponiendo que la última columna con valores numéricos es la nota final
    columna_nota = None
    if otras_cols:
        columna_nota = otras_cols[-1]

    for col in otras_cols:
        if col != columna_nota:
            # Simplificamos: si es una columna numérica, la consideramos subtema
            try:
                if pd.api.types.is_numeric_dtype(df[col]):
                    subtemas.append(col)
            except:
                continue # Ignorar si hay un error de dtype (por ejemplo, columna totalmente vacía)

    return subtemas

# --- Rutas de la Aplicación ---

@app.route('/', methods=['GET', 'POST'])
def subir_archivo():
    """Ruta para subir el archivo Excel y guardar los datos de todas las hojas en la sesión (ANALISIS DE TAREAS)."""
    if request.method == 'POST':
        file = request.files.get('archivo_excel')
        if not file or file.filename == '':
            return redirect(request.url)

        try:
            # Lógica de procesamiento de tu código original (Actividades/Tareas)
            xls_dict = pd.read_excel(io.BytesIO(file.read()), header=2, sheet_name=None) 
            
            df_list = []
            for sheet_name, sheet_df in xls_dict.items():
                df_list.append(sheet_df)
                
            df = pd.concat(df_list, ignore_index=True)
            
            df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
            df = df.rename(columns={
                c: c.capitalize() for c in df.columns if isinstance(c, str) and c.lower().strip() in ['cédula', 'nombre', 'curso']
            })

            if 'Curso' not in df.columns:
                 raise ValueError("El archivo Excel debe contener una columna llamada 'Curso'.")
            
            # Almacenamiento para Análisis de TAREAS/ACTIVIDADES
            session['datos_excel'] = df.to_json(orient='split')
            
            return redirect(url_for('mostrar_resultados'))

        except Exception as e:
            print(f"Error al procesar el archivo: {e}")
            return render_template('index.html', error=f"Error al procesar el archivo. Detalle: {e}")

    return render_template('index.html', error=None)

@app.route('/resultados', methods=['GET', 'POST'])
def mostrar_resultados():
    """Ruta principal para mostrar filtros, gráficos y resultados estadísticos (ANALISIS DE TAREAS/ACTIVIDADES)."""
    if 'datos_excel' not in session:
        return redirect(url_for('subir_archivo'))

    try:
        df = pd.read_json(session['datos_excel'], orient='split')
    except Exception:
        # Si falla la carga, limpiar e ir al inicio (Cargar Tareas)
        session.pop('datos_excel', None)
        return redirect(url_for('subir_archivo')) 

    # --- Lógica de filtrado y visualización de resultados.html (mantenida) ---
    
    # Preparación de listas de cursos y tareas para los filtros
    if 'Curso' in df.columns:
        df['Curso'] = df['Curso'].astype(str)
        cursos_disponibles = sorted(df['Curso'].unique())
    else:
        cursos_disponibles = []
        
    tareas_disponibles = identificar_columnas_tareas(df)
    
    graficos_htmls = {} 
    indicadores_agrupados_por_tarea = {}
    estadisticas_agrupadas_por_tarea = {}

    if request.method == 'POST':
        cursos_seleccionados = request.form.getlist('cursos')
        tareas_seleccionadas = request.form.getlist('tareas')
        tipo_grafico = request.form.get('tipo_grafico')
        
        if cursos_seleccionados and tareas_seleccionadas and 'Curso' in df.columns:
            
            df_filtrado = df[df['Curso'].isin(cursos_seleccionados)].copy()
            
            # Reestructuración de datos (melt) para el análisis
            df_grafico_base = df_filtrado.melt(
                id_vars=['Curso'], 
                value_vars=tareas_seleccionadas, 
                var_name='Tarea', 
                value_name='Calificacion'
            ).dropna(subset=['Calificacion']) 

            # Asegurar que la calificación es entera para el conteo de frecuencias
            df_grafico_base['Calificacion'] = df_grafico_base['Calificacion'].astype(int)
            
            # === CÁLCULO DE PROMEDIOS Y ESTADÍSTICAS ===
            promedios = df_grafico_base.groupby(['Curso', 'Tarea'])['Calificacion'].mean().reset_index()

            for tarea in tareas_seleccionadas:
                # Indicadores de promedio
                indicadores_agrupados_por_tarea[tarea] = []
                promedios_tarea = promedios[promedios['Tarea'] == tarea]
                for _, row in promedios_tarea.iterrows():
                    indicadores_agrupados_por_tarea[tarea].append({
                        'curso': row['Curso'],
                        'promedio': row['Calificacion']
                    })

                # Estadísticas de detalle
                estadisticas_agrupadas_por_tarea[tarea] = {}
                for curso in cursos_seleccionados:
                    if tarea in df_filtrado.columns:
                        conteo_calificaciones = df_filtrado[df_filtrado['Curso'] == curso][tarea].dropna().astype(int).value_counts().sort_index()
                        estadisticas_agrupadas_por_tarea[tarea][curso] = conteo_calificaciones.to_dict()
            
            
            # === GENERACIÓN DE UN GRÁFICO SEPARADO PARA CADA TAREA ===
            etiquetas_grafico = {'Calificacion': 'Nota (0-10)', 'Cantidad_Estudiantes': 'Nº Estudiantes', 'Curso': 'Curso'} 

            for tarea in tareas_seleccionadas:
                df_tarea = df_grafico_base[df_grafico_base['Tarea'] == tarea].copy()
                
                df_frecuencias = df_tarea.groupby(['Calificacion', 'Curso']).size().reset_index(name='Cantidad_Estudiantes')
                
                titulo_grafico = f'{tipo_grafico.capitalize()} de Frecuencias de Calificaciones para: {tarea}'
                
                if tipo_grafico == 'barras':
                    fig = px.bar(df_frecuencias, x='Calificacion', y='Cantidad_Estudiantes', color='Curso', 
                                 barmode='group', 
                                 title=titulo_grafico,
                                 labels=etiquetas_grafico)
                else: # Tendencias
                    fig = px.line(df_frecuencias, x='Calificacion', y='Cantidad_Estudiantes', color='Curso',
                                  title=titulo_grafico, markers=True,
                                  labels=etiquetas_grafico)
                
                fig.update_layout(yaxis_title="Cantidad de Estudiantes", xaxis_title="Calificación (Nota)")
                fig.update_xaxes(tick0=0, dtick=1, range=[-0.5, 10.5])
                
                graficos_htmls[tarea] = fig.to_html(full_html=False)


    return render_template('resultados.html', 
                            cursos=cursos_disponibles, 
                            tareas=tareas_disponibles,
                            graficos_htmls=graficos_htmls,
                            indicadores=indicadores_agrupados_por_tarea,
                            estadisticas=estadisticas_agrupadas_por_tarea)

# ***********************************
# ** NUEVA RUTA PARA EVALUACIONES **
# ***********************************
@app.route('/evaluaciones', methods=['GET', 'POST'])
def mostrar_evaluaciones():
    """Ruta para la nueva interfaz y procesamiento de datos de Evaluaciones/Subtemas."""
    
    # 1. Manejo de Subida de Archivo (POST)
    if request.method == 'POST' and 'archivo_evaluaciones' in request.files:
        file = request.files.get('archivo_evaluaciones')
        
        if not file or file.filename == '':
            return redirect(url_for('mostrar_evaluaciones'))

        try:
            # Leer el archivo, asumiendo una única hoja para Evaluaciones
            file_data = file.read()
            df = pd.read_excel(io.BytesIO(file_data), header=2) 
            
            # Limpieza y estandarización de nombres de columnas
            df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
            df = df.rename(columns={
                c: c.capitalize() for c in df.columns if isinstance(c, str) and c.lower().strip() in ['cédula', 'nombre', 'curso']
            })

            if 'Curso' not in df.columns:
                 raise ValueError("El archivo Excel debe contener una columna llamada 'Curso'.")
            
            # Almacenamiento para Análisis de EVALUACIONES
            session['datos_evaluaciones'] = df.to_json(orient='split')
            
            # Redirigir a GET para mostrar la interfaz de filtros
            return redirect(url_for('mostrar_evaluaciones')) 

        except Exception as e:
            error_msg = f"Error al procesar el archivo. Asegúrate de que tenga el formato correcto (header en fila 3). Detalle: {e}"
            print(error_msg)
            return render_template('evaluaciones.html', error_general=error_msg, cursos=[], subtemas=[], graficos_htmls={}, indicadores={})

    # 2. Manejo de Visualización y Análisis (GET y POST de filtros)
    if 'datos_evaluaciones' not in session:
        # Mostrar interfaz vacía para subir el archivo
        return render_template('evaluaciones.html', error_general=None, cursos=[], subtemas=[], graficos_htmls={}, indicadores={}, estadisticas={})

    try:
        # Carga de datos de Evaluación desde la sesión
        df = pd.read_json(session['datos_evaluaciones'], orient='split')
    except Exception:
        session.pop('datos_evaluaciones', None)
        return redirect(url_for('mostrar_evaluaciones'))

    
    # Preparación de listas de cursos y subtemas para los filtros
    if 'Curso' in df.columns:
        df['Curso'] = df['Curso'].astype(str)
        cursos_disponibles = sorted(df['Curso'].unique())
    else:
        cursos_disponibles = []
        
    subtemas_disponibles = identificar_columnas_evaluaciones(df) # Usar la función de identificación
    
    graficos_htmls = {} 
    indicadores_agrupados_por_subtema = {}
    estadisticas_agrupadas_por_subtema = {}
    error_grafico = None
    
    # 2.1 Procesamiento de Filtros (POST de Análisis)
    if request.method == 'POST' and 'generar_analisis' in request.form:
        cursos_seleccionados = request.form.getlist('cursos')
        subtemas_seleccionados = request.form.getlist('subtemas')
        tipo_grafico = request.form.get('tipo_grafico')
        
        if not cursos_seleccionados or not subtemas_seleccionados:
             error_grafico = "Debes seleccionar al menos un Curso y un Subtema para generar el análisis."
        else:
            df_filtrado = df[df['Curso'].isin(cursos_seleccionados)].copy()
            
            # Reestructuración de datos (melt) para el análisis
            df_grafico_base = df_filtrado.melt(
                id_vars=['Curso'], 
                value_vars=subtemas_seleccionados, 
                var_name='Subtema', 
                value_name='Acierto'
            ).dropna(subset=['Acierto']) 
            
            if df_grafico_base.empty:
                error_grafico = "No hay datos de acierto válidos para los filtros seleccionados."
            else:
                # Se asume que Acierto es 0 o 1
                df_grafico_base['Acierto'] = df_grafico_base['Acierto'].fillna(0).astype(int)
                
                # === CÁLCULO DE PROMEDIOS (TASA DE ACIERTO 0-1) ===
                promedios = df_grafico_base.groupby(['Curso', 'Subtema'])['Acierto'].mean().reset_index()

                for subtema in subtemas_seleccionados:
                    # Indicadores de promedio (escalado a 0-10)
                    indicadores_agrupados_por_subtema[subtema] = []
                    promedios_subtema = promedios[promedios['Subtema'] == subtema]
                    for _, row in promedios_subtema.iterrows():
                        indicadores_agrupados_por_subtema[subtema].append({
                            'curso': row['Curso'],
                            'promedio': row['Acierto'] * 10 # Escalar a 0-10 para el semáforo
                        })

                    # Estadísticas de detalle (Conteo de 0s y 1s)
                    estadisticas_agrupadas_por_subtema[subtema] = {}
                    for curso in cursos_seleccionados:
                        df_curso = df_filtrado[df_filtrado['Curso'] == curso]
                        if subtema in df_curso.columns:
                            # Conteo de 0s y 1s
                            conteo_acierto = df_curso[subtema].value_counts().to_dict()
                            
                            estadisticas_agrupadas_por_subtema[subtema][curso] = {
                                'Aciertos (1)': conteo_acierto.get(1, 0),
                                'Errores (0)': conteo_acierto.get(0, 0)
                            }
                
                # === GENERACIÓN DE GRÁFICOS (Tasa de Acierto Global) ===
                # Agrupar por subtema y curso para el gráfico. Se usará el promedio de acierto.
                df_frecuencias = promedios.rename(columns={'Acierto': 'Tasa_Acierto_Promedio'})

                for subtema in subtemas_seleccionados:
                    df_subtema = df_frecuencias[df_frecuencias['Subtema'] == subtema].copy()
                    
                    titulo_grafico = f'{tipo_grafico.capitalize()} de Tasa de Acierto (0-1) para: {subtema}'
                    
                    # Usar el promedio de aciertos (0-1) en el eje Y
                    if tipo_grafico == 'barras':
                        fig = px.bar(df_subtema, x='Curso', y='Tasa_Acierto_Promedio', color='Curso', 
                                     title=titulo_grafico,
                                     labels={'Tasa_Acierto_Promedio': 'Tasa de Acierto (0-1)', 'Curso': 'Curso'})
                    else: # Tendencias (puede ser menos relevante para este tipo de datos, pero se mantiene la opción)
                        fig = px.bar(df_subtema, x='Curso', y='Tasa_Acierto_Promedio', color='Curso',
                                     title=titulo_grafico,
                                     labels={'Tasa_Acierto_Promedio': 'Tasa de Acierto (0-1)', 'Curso': 'Curso'})
                    
                    fig.update_layout(yaxis_title="Tasa de Acierto (0-1)", xaxis_title="Curso")
                    fig.update_yaxes(range=[0, 1.0])
                    
                    graficos_htmls[subtema] = fig.to_html(full_html=False)

    
    # 2.2 Renderizado de la página
    context = {
        'cursos': cursos_disponibles, 
        'subtemas': subtemas_disponibles,
        'graficos_htmls': graficos_htmls,
        'indicadores': indicadores_agrupados_por_subtema,
        'estadisticas': estadisticas_agrupadas_por_subtema,
        'error_general': None,
        'error_grafico': error_grafico,
        'request_form': request.form # Pasar el formulario para mantener selecciones
    }

    return render_template('evaluaciones.html', **context)


@app.route('/limpiar')
def limpiar_datos():
    """Ruta para borrar los datos de Actividades y redirigir a la subida de archivos."""
    session.pop('datos_excel', None)
    return redirect(url_for('subir_archivo'))

@app.route('/limpiar_evaluaciones')
def limpiar_evaluaciones():
    """Ruta para borrar los datos de Evaluaciones y redirigir a la interfaz de Evaluaciones."""
    session.pop('datos_evaluaciones', None)
    return redirect(url_for('mostrar_evaluaciones'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port, debug=False)
