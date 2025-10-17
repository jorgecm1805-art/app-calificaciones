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
    """Filtra y devuelve los nombres de las columnas que representan actividades o tareas."""
    columnas_identificacion = ['cedula', 'nombre', 'curso']
    return [
        col for col in df.columns 
        if isinstance(col, str) and col.lower().strip() not in columnas_identificacion
    ]

# --- Rutas de la Aplicación ---

@app.route('/', methods=['GET', 'POST'])
def subir_archivo():
    """Ruta para subir el archivo Excel y guardar los datos de todas las hojas en la sesión."""
    if request.method == 'POST':
        file = request.files.get('archivo_excel')
        if not file or file.filename == '':
            return redirect(request.url)

        try:
            # Lectura de Excel para TODAS las hojas (sheet_name=None)
            # Esto devuelve un diccionario: {nombre_hoja: DataFrame}
            xls_dict = pd.read_excel(io.BytesIO(file.read()), header=2, sheet_name=None) 
            
            # Combinar todos los DataFrames en uno solo
            # Esto es necesario si los datos de los cursos están distribuidos en diferentes hojas.
            df_list = []
            for sheet_name, sheet_df in xls_dict.items():
                # Añade una columna opcional para identificar la hoja de origen si es necesario
                # sheet_df['Hoja'] = sheet_name 
                df_list.append(sheet_df)
                
            # Concatenar todos los DataFrames en un único DataFrame para el análisis
            df = pd.concat(df_list, ignore_index=True)
            
            # Limpieza y estandarización de nombres de columnas
            df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
            df = df.rename(columns={
                c: c.capitalize() for c in df.columns if isinstance(c, str) and c.lower().strip() in ['cédula', 'nombre', 'curso']
            })

            if 'Curso' not in df.columns:
                 raise ValueError("El archivo Excel debe contener una columna llamada 'Curso'.")
            
            # Almacenamiento del DataFrame combinado en la sesión
            session['datos_excel'] = df.to_json(orient='split')
            
            return redirect(url_for('mostrar_resultados'))

        except Exception as e:
            # Manejo de error al procesar el archivo
            print(f"Error al procesar el archivo: {e}")
            return render_template('index.html', error=f"Error al procesar el archivo. Detalle: {e}")

    return render_template('index.html', error=None)

@app.route('/resultados', methods=['GET', 'POST'])
def mostrar_resultados():
    """Ruta principal para mostrar filtros, gráficos y resultados estadísticos."""
    if 'datos_excel' not in session:
        return redirect(url_for('subir_archivo'))

    try:
        # Carga de datos desde la sesión
        df = pd.read_json(session['datos_excel'], orient='split')
    except Exception:
        return redirect(url_for('limpiar_datos')) 

    
    # Preparación de listas de cursos y tareas para los filtros
    if 'Curso' in df.columns:
        df['Curso'] = df['Curso'].astype(str)
        cursos_disponibles = sorted(df['Curso'].unique())
    else:
        cursos_disponibles = []
        
    tareas_disponibles = identificar_columnas_tareas(df)
    
    grafico_html = ""
    indicadores_agrupados_por_tarea = {}
    estadisticas_agrupadas_por_tarea = {}

    if request.method == 'POST':
        cursos_seleccionados = request.form.getlist('cursos')
        tareas_seleccionadas = request.form.getlist('tareas')
        tipo_grafico = request.form.get('tipo_grafico')
        
        if cursos_seleccionados and tareas_seleccionadas and 'Curso' in df.columns:
            
            df_filtrado = df[df['Curso'].isin(cursos_seleccionados)].copy()
            
            # Reestructuración de datos (melt) para el análisis
            df_grafico = df_filtrado.melt(
                id_vars=['Curso'], 
                value_vars=tareas_seleccionadas, 
                var_name='Tarea', 
                value_name='Calificacion'
            ).dropna(subset=['Calificacion']) 
            
            
            # Aplicación de orden forzado a las tareas para el eje X del gráfico
            df_grafico['Tarea'] = pd.Categorical(
                df_grafico['Tarea'], 
                categories=tareas_seleccionadas, 
                ordered=True
            )
            
            # Cálculo de promedios por Curso y Tarea
            promedios = df_grafico.groupby(['Curso', 'Tarea'])['Calificacion'].mean().reset_index()

            # Estructuración de indicadores por Tarea
            for tarea in tareas_seleccionadas:
                indicadores_agrupados_por_tarea[tarea] = []
                promedios_tarea = promedios[promedios['Tarea'] == tarea]
                
                for _, row in promedios_tarea.iterrows():
                    indicadores_agrupados_por_tarea[tarea].append({
                        'curso': row['Curso'],
                        'promedio': row['Calificacion']
                    })

            # Estructuración de estadísticas de distribución por Tarea
            for tarea in tareas_seleccionadas:
                estadisticas_agrupadas_por_tarea[tarea] = {}
                
                for curso in cursos_seleccionados:
                    if tarea in df_filtrado.columns:
                        # Conteo de la frecuencia de cada calificación por Curso
                        conteo_calificaciones = df_filtrado[df_filtrado['Curso'] == curso][tarea].dropna().astype(int).value_counts().sort_index()
                        estadisticas_agrupadas_por_tarea[tarea][curso] = conteo_calificaciones.to_dict()
            
            
            # Definición de etiquetas personalizadas para el tooltip del gráfico Plotly
            etiquetas_grafico = {'Tarea': 'Actividad', 'Calificacion': 'Promedio'} 

            # Configuración y generación del gráfico (Barras o Tendencias)
            if tipo_grafico == 'barras':
                fig = px.bar(promedios, x='Tarea', y='Calificacion', color='Curso', 
                             barmode='group', 
                             title='Promedio de Calificaciones por Curso y Tarea',
                             labels=etiquetas_grafico)
            else: 
                fig = px.line(promedios, x='Tarea', y='Calificacion', color='Curso',
                              title='Tendencia de Promedios por Curso y Tarea', markers=True,
                              labels=etiquetas_grafico)
            
            fig.update_layout(yaxis_title="Promedio de Calificación", xaxis_title="Evaluación")
            # Conversión del gráfico a HTML para mostrar en Jinja2
            grafico_html = fig.to_html(full_html=False)


    return render_template('resultados.html', 
                           cursos=cursos_disponibles, 
                           tareas=tareas_disponibles,
                           grafico_html=grafico_html,
                           indicadores=indicadores_agrupados_por_tarea,
                           estadisticas=estadisticas_agrupadas_por_tarea)


@app.route('/limpiar')
def limpiar_datos():
    """Ruta para borrar los datos de la sesión y redirigir a la subida de archivos."""
    session.pop('datos_excel', None)
    return redirect(url_for('subir_archivo'))

if __name__ == '__main__':
    # Obtiene el puerto del entorno (como Render) o usa 5000 por defecto
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port, debug=False)