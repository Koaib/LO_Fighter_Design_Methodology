import numpy as np
from stl import mesh

# def stl_converter(file_path):
#     # Lendo o arquivo com o stl mesh
#     # file_path = "stl-module\\box.stl"
#     stl_mesh = mesh.Mesh.from_file(file_path)

#     # Listando os vértices únicos
#     vertices = stl_mesh.points.reshape((-1, 3))
#     indexes = np.unique(vertices, axis=0, return_index=True)[1]
#     coordinates = vertices[indexes]

#     # print(coordinates)

#     # Verificando os vértices que compõem cada face e calculando o ilum flag
#     facets = []

#     for i, face in enumerate(stl_mesh.vectors):
#         vertices_face = []
#         vertices_face.append(i+1)
        
#         # Checando se a face é parte de uma estrutura fechada
#         is_closed_structure = any((coordinates == face[0]).all(axis=1)) and any((coordinates == face[1]).all(axis=1)) and any(
#             (coordinates == face[2]).all(axis=1))

#         # Calculando a normal da face
#         normal = np.cross(face[1] - face[0], face[2] - face[0])
        
#         if normal[2] < 0:
#             normal = -normal  # Garantindo os pontos normais para fora
            
#         ilum_flag = 1 if is_closed_structure else 0
        
#         for vertex in face:
#             index = int(np.where((coordinates == vertex).all(axis=1))[0])
#             vertices_face.append(index + 1)
        
#         vertices_face.append(ilum_flag)
#         vertices_face.append(0)  # Rs --> Vamos receber esse parâmetro a partir do input via interface
        
#         facets.append(vertices_face)

#     facets = np.array(facets)

#     # print(facets)

#     # Salvar arquivos como .txt
#     np.savetxt("coordinates.txt", coordinates, fmt="%f", delimiter=" ")
#     np.savetxt("facets.txt", facets, fmt="%d", delimiter=" ")

def stl_converter(file_path):
    stl_mesh = mesh.Mesh.from_file(file_path)

    # (ntria*3, 3) — 3 vertices per triangle, in face order
    all_verts = stl_mesh.vectors.reshape(-1, 3)
    ntria = len(stl_mesh.vectors)

    # single vectorized pass: unique vertices + index of each vertex-instance
    # into that unique array. Replaces the old per-face np.where/any linear
    # scans (O(ntria * nverts)) with one O(n log n) operation.
    coordinates, inverse = np.unique(all_verts, axis=0, return_inverse=True)
    node_idx = inverse.reshape(-1, 3) + 1   # (ntria, 3), 1-indexed to match old format

    # NOTE: the old "is_closed_structure" check tested whether each face's
    # vertices exist in `coordinates` -- but coordinates is built from those
    # same faces, so it was always True by construction (dead computation).
    # ilum_flag is therefore always 1; hardcoded here instead of recomputed.
    face_ids  = np.arange(1, ntria + 1).reshape(-1, 1)
    ilum_flag = np.ones((ntria, 1), dtype=int)
    rs_col    = np.zeros((ntria, 1), dtype=int)   # Rs set later via UI/params, same as before

    facets = np.hstack([face_ids, node_idx, ilum_flag, rs_col]).astype(int)

    np.savetxt("coordinates.txt", coordinates, fmt="%f", delimiter=" ")
    np.savetxt("facets.txt", facets, fmt="%d", delimiter=" ")