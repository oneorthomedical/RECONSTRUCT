import os, sys
import cv2
import numpy as np
from scipy.spatial import Delaunay
from gi.repository import GExiv2
import draw, vtk_cloud, model
import matplotlib.pyplot as plt

def load_images(filename1, filename2):
	'''Loads 2 images.'''
	# img1 and img2 are HxWx3 arrays (rows, columns, 3-colour channels)
	img1 = cv2.imread(filename1)
	img2 = cv2.imread(filename2)
	img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2RGB)
	img2 = cv2.cvtColor(img2, cv2.COLOR_BGR2RGB)

	return img1, img2

def build_calibration_matrices(i, prev_sensor, filename1, filename2):
	'''Extract exif metadata from image files, and use them to build the 2 calibration matrices.'''

	def validate(user_input):
		'''Checks if each character in the string (except periods) are integers.'''
		for i in user_input.translate(None, '.'):
			if not 48 <= ord(i) <= 57:
				return False
		return True

	def get_sensor_sizes(i, prev_sensor, metadata1, metadata2):
		'''Displays camera model based on EXIF data. Gets user's input on the width of the camera's sensor.'''
		# focal length in pixels = (image width in pixels) * (focal length in mm) / (CCD width in mm)
		if i == 0:
			print "Camera %s is a %s." % (str(i+1), metadata1['Exif.Image.Model'])
			sensor_1 = raw_input("What is the width (in mm) of camera %s's sensor? > " % str(i+1))
			print "Camera %s is a %s." % (str(i+2), metadata2['Exif.Image.Model'])
			sensor_2 = raw_input("What is the width (in mm) of camera %s's sensor? > " % str(i+2))
		elif i >= 1:
			sensor_1 = str(prev_sensor)
			print "Camera %s is a %s." % (str(i+2), metadata2['Exif.Image.Model'])
			sensor_2 = raw_input("What is the width (in mm) of camera %s's sensor? > " % str(i+2))

		if validate(sensor_1) and validate(sensor_2):
			return float(sensor_1), float(sensor_2)

	metadata1 = GExiv2.Metadata(filename1)
	metadata2 = GExiv2.Metadata(filename2)

	if metadata1.get_supports_exif() and metadata2.get_supports_exif():
		sensor_1, sensor_2 = get_sensor_sizes(i, prev_sensor, metadata1, metadata2)
	else:
		if metadata1.get_supports_exif() == False:
			print "Exif data not available for ", filename1
		if metadata2.get_supports_exif() == False:
			print "Exif data not available for ", filename2
		sys.exit("Please try again.")

	# Calibration matrix for camera 1 (K1)
	f1_mm = metadata1.get_focal_length()
	w1 = metadata1.get_pixel_width()
	h1 = metadata1.get_pixel_height()
	f1_px = (w1 * f1_mm) / sensor_1
	K1 = np.array([[f1_px, 0, w1/2], [0, f1_px, h1/2], [0,0,1]])

	# Calibration matrix for camera 2 (K2)
	f2_mm = metadata2.get_focal_length()
	w2 = metadata2.get_pixel_width()
	h2 = metadata2.get_pixel_height()
	f2_px = (w2 * f2_mm) / sensor_2
	K2 = np.array([[f2_px, 0, w2/2], [0, f2_px, h2/2], [0,0,1]])
	return sensor_2, K1, K2

def gray_images(img1, img2):
	'''Convert images to grayscale if the images are found.'''
	try:
		img1_gray = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY)
		img2_gray = cv2.cvtColor(img2, cv2.COLOR_RGB2GRAY)
	except:
		print "Image not found!"

	return img1_gray, img2_gray

def find_keypoints_descriptors(img1, img2):
	'''Detects keypoints and computes their descriptors.'''
	# initiate detector
	detector = cv2.SURF()

	# find the keypoints and descriptors
	kp1, des1 = detector.detectAndCompute(img1, None)
	kp2, des2 = detector.detectAndCompute(img2, None)

	return kp1, des1, kp2, des2

def match_keypoints(kp1, des1, kp2, des2):
	'''Matches the descriptors in one image with those in the second image using
	the Fast Library for Approximate Nearest Neighbours (FLANN) matcher.'''
	MIN_MATCH_COUNT = 10

	# FLANN parameters
	FLANN_INDEX_KDTREE = 0
	index_params = dict(algorithm = FLANN_INDEX_KDTREE, trees = 5)
	search_params = dict(checks=50)   # or pass empty dictionary

	flann = cv2.FlannBasedMatcher(index_params,search_params)
	matches = flann.knnMatch(np.asarray(des1, np.float32), np.asarray(des2, np.float32), k=2)

	# store all the good matches as per Lowe's ratio test
	good_matches = []
	for m, n in matches:
	    if m.distance < 0.7 * n.distance:
	        good_matches.append(m)

	if len(good_matches) > MIN_MATCH_COUNT:
	    src_pts = np.float32([ kp1[m.queryIdx].pt for m in good_matches ]).reshape(-1,1,2)
	    dst_pts = np.float32([ kp2[m.trainIdx].pt for m in good_matches ]).reshape(-1,1,2)
	else:
	    print "Not enough matches were found - %d/%d" % (len(good_matches), MIN_MATCH_COUNT)

	# src_pts and dst_pts are Nx1x2 arrays
	return src_pts, dst_pts

def normalize_pts(K1, K2, src_pts, dst_pts):
	# convert to 3xN arrays by making the points homogeneous
	src_pts = np.vstack((np.array([ pt[0] for pt in src_pts ]).T, np.ones(src_pts.shape[0])))
	dst_pts = np.vstack((np.array([ pt[0] for pt in dst_pts ]).T, np.ones(dst_pts.shape[0])))

	# normalize with the calibration matrices
	# norm_pts1 and norm_pts2 are 3xN arrays
	norm_pts1 = np.dot(np.linalg.inv(K1), src_pts)
	norm_pts2 = np.dot(np.linalg.inv(K2), dst_pts)

	# convert back to Nx1x2 arrays
	norm_pts1 = np.array([ [pt] for pt in norm_pts1[:2].T ])
	norm_pts2 = np.array([ [pt] for pt in norm_pts2[:2].T ])

	return norm_pts1, norm_pts2

def find_essential_matrix(K, norm_pts1, norm_pts2):
	# convert to Nx2 arrays for findFundamentalMat
	norm_pts1 = np.array([ pt[0] for pt in norm_pts1 ])
	norm_pts2 = np.array([ pt[0] for pt in norm_pts2 ])
	F, mask = cv2.findFundamentalMat(norm_pts1, norm_pts2, cv2.RANSAC)
	E = np.dot(K.T, np.dot(F, K))

	return E, mask

def find_projection_matrices(E):
	'''Compute the second camera matrix (assuming the first camera matrix = [I 0]).
	Output is a list of 4 possible camera matrices for P2.'''
	# the first camera matrix is assumed to be the identity matrix
	P1 = np.array([[1,0,0,0], [0,1,0,0], [0,0,1,0]], dtype=float)

	# make sure E is rank 2
	U, S, V = np.linalg.svd(E)
	if np.linalg.det(np.dot(U, V)) < 0:
		V = -V
	E = np.dot(U, np.dot(np.diag([1,1,0]), V))

	# create matrices
	W = np.array([[0,-1,0], [1,0,0], [0,0,1]])

	# return all four solutions
	P2 = [np.vstack( (np.dot(U,np.dot(W,V)).T, U[:,2]) ).T, 
		  np.vstack( (np.dot(U,np.dot(W,V)).T, -U[:,2]) ).T,
		  np.vstack( (np.dot(U,np.dot(W.T,V)).T, U[:,2]) ).T, 
		  np.vstack( (np.dot(U,np.dot(W.T,V)).T, -U[:,2]) ).T]

	return P1, P2

def refine_points(norm_pts1, norm_pts2, E, mask):
	'''Refine the coordinates of the corresponding points using the Optimal Triangulation Method.'''
	# select only inlier points
	norm_pts1 = norm_pts1[mask.ravel()==1]
	norm_pts2 = norm_pts2[mask.ravel()==1]

	# convert to 1xNx2 arrays for cv2.correctMatches
	refined_pts1 = np.array([ [pt[0] for pt in norm_pts1 ] ])
	refined_pts2 = np.array([ [pt[0] for pt in norm_pts2 ] ])
	refined_pts1, refined_pts2 = cv2.correctMatches(E, refined_pts1, refined_pts2)

	# outputs are also 1xNx2 arrays
	return refined_pts1, refined_pts2

def get_colours(img1, P1, homog_3D):
	'''Extract RGB data from the original images and store them in new arrays.'''
	# project 3D points back to the image plane
	# camera.project returns a 3xN array of homogeneous points --> convert to Nx3 array 
	camera = draw.Camera(P1)
	img_pts = camera.project(homog_3D)[:2].T

	# extract RGB information and store in new arrays with the coordinates
	img_colours = np.array([ img1[ pt[1] ][ pt[0] ] for pt in img_pts ])

	return img_pts, img_colours

def triangulate_points(P1, P2, refined_pts1, refined_pts2):
	'''Reconstructs 3D points by triangulation using Direct Linear Transformation.'''
	# convert to 2xN arrays
	img1_pts = refined_pts1[0].T
	img2_pts = refined_pts2[0].T

	# pick the P2 matrix with the most scene points in front of the cameras after triangulation
	ind = 0
	maxres = 0
	for i in range(4):
		# triangulate inliers and compute depth for each camera
		homog_3D = cv2.triangulatePoints(P1, P2[i], img1_pts, img2_pts)
		# the sign of the depth is the 3rd value of the image point after projecting back to the image
		d1 = np.dot(P1, homog_3D)[2]
		d2 = np.dot(P2[i], homog_3D)[2]
		
		if sum(d1 > 0) + sum(d2 < 0) > maxres:
			maxres = sum(d1 > 0) + sum(d2 < 0)
			ind = i
			infront = (d1 > 0) & (d2 < 0)

	# triangulate inliers and keep only points that are in front of both cameras
	# homog_3D is a 4xN array of reconstructed points in homogeneous coordinates
	# pts_3D is a Nx3 array
	homog_3D = cv2.triangulatePoints(P1, P2[ind], img1_pts, img2_pts)
	homog_3D = homog_3D[:, infront]
	homog_3D = homog_3D / homog_3D[3]
	pts_3D = np.array(homog_3D[:3]).T

	return homog_3D, pts_3D

def delaunay(homog_3D, pts_3D):
	'''Delaunay tetrahedralization of 3D points.'''
	
	def remove_outliers(pts_3D):
		'''Remove points that are too far away from the median.'''
		x, y, z = pts_3D.T[0], pts_3D.T[1], pts_3D.T[2]
		x_med, y_med, z_med = np.median(x), np.median(y), np.median(z)
		x_std, y_std, z_std = np.std(x), np.std(y), np.std(z)
		print "medians: ", x_med, y_med, z_med
		print "std devs: ", x_std, y_std, z_std
		x_mask = [ True if ( x_med - 1 * x_std < coord < x_med + 1 * x_std) else False for coord in x ]
		y_mask = [ True if ( y_med - 1 * y_std < coord < y_med + 1 * y_std) else False for coord in y ]
		z_mask = [ True if ( z_med - 1 * z_std < coord < z_med + 1 * z_std) else False for coord in z ]
		mask = [ all(tup) for tup in zip(x_mask, y_mask, z_mask) ]
		
		count = 0
		for _bool in mask:
			if _bool:
				count += 1
		print count

		pts_3D = [ pt[0] for pt in zip(pts_3D, mask) if pt[1] ]
		print len(pts_3D)

		return pts_3D
	
	filtered_pts = remove_outliers(pts_3D)

	tetra = Delaunay(pts_3D)
	print tetra.nsimplex
	# # project 3D pts back to 2D for plotting in matplotlib
	# camera = draw.Camera(P)
	# proj_pts = camera.project(homog_3D).T

	# # plot x-coords, y-coords and simplices
	# plt.triplot(proj_pts[:,0], proj_pts[:,1], tetra.simplices)
	# plt.plot(proj_pts[:,0], proj_pts[:,1], 'o')
	# plt.show()

	faces = set()

	def add_face(v1, v2, v3):
		'''Makes sure the indices stored in each face is always in the order small --> large.'''
		face_vertices = [v1, v2, v3]

		for vertex in face_vertices:
			_min = min(face_vertices)
			_max = max(face_vertices)

		if set([ face_vertices.index(_min), face_vertices.index(_max) ]) == set([0,1]):
			_mid = face_vertices[2]
		elif set([ face_vertices.index(_min), face_vertices.index(_max) ]) == set([1,2]):
			_mid = face_vertices[0]
		else:
			_mid = face_vertices[1]

		faces.add( (_min, _mid, _max) )

	for i in xrange(tetra.nsimplex):
		# tetra.simplices is a Nx4 array. Each row contains the indices of points that make up a tetrahedron
		# each face added is a tuple containing the indices of the points that make up that face 
		add_face(tetra.simplices[i,0], tetra.simplices[i,1], tetra.simplices[i,2])
		add_face(tetra.simplices[i,1], tetra.simplices[i,3], tetra.simplices[i,2])
		add_face(tetra.simplices[i,0], tetra.simplices[i,3], tetra.simplices[i,1])
		add_face(tetra.simplices[i,0], tetra.simplices[i,2], tetra.simplices[i,3])

	print "# faces: ", len(faces)
	faces = list(faces)

	# draw.draw_mesh(pts_3D,faces)

	# points
	points = np.array([ pts_3D[vertex] for face in faces for vertex in face ])
	print points.shape

	# triangles
	faces = np.array(faces)
	triangles = faces
	print triangles.shape

	actor = vtk_cloud.vtk_triangles(points, triangles)
	vtk_cloud.vtk_basic([actor])
	# vtk_cloud.vtk_show_points(pts_3D)
	# return faces

def gen_pt_cloud(i, prev_sensor, image1, image2):
	'''Generates a point cloud for a pair of images. Generated point cloud is on the local coordinate system.'''
	img1, img2 = load_images(image1, image2)
	sensor_i, K1, K2 = build_calibration_matrices(i, prev_sensor, image1, image2)

	img1_gray, img2_gray = gray_images(img1, img2)
	kp1, des1, kp2, des2 = find_keypoints_descriptors(img1_gray, img2_gray)
	src_pts, dst_pts = match_keypoints(kp1, des1, kp2, des2)
	norm_pts1, norm_pts2 = normalize_pts(K1, K2, src_pts, dst_pts)

	E, mask = find_essential_matrix(K1, norm_pts1, norm_pts2)
	P1, P2 = find_projection_matrices(E)

	refined_pts1, refined_pts2 = refine_points(norm_pts1, norm_pts2, E, mask)
	homog_3D, pts_3D = triangulate_points(P1, P2, refined_pts1, refined_pts2)
	delaunay(homog_3D, pts_3D)

	img_pts, img_colours = get_colours(img1, P1, homog_3D)

	return sensor_i, K1, P1, homog_3D, pts_3D, img_pts, img_colours



def main():
	'''Loop through each pair of images, find point correspondences and generate 3D point cloud.
	Multiply each point cloud by the 4x4 transformation matrix up to that point 
	to get the 3D point (as seen by camera 1) and append this point to the overall point cloud.'''
	# directory = 'images/ucd_building3_all'
	# images = ['images/ucd_coffeeshack_all/00000000.JPG', 'images/ucd_coffeeshack_all/00000001.JPG']
	# images = ['images/data/alcatraz1.jpg', 'images/data/alcatraz2.jpg']
	# images = ['images/ucd_building4_all/00000000.jpg', 'images/ucd_building4_all/00000001.jpg']
	# images = sorted([ str(directory + "/" + img) for img in os.listdir(directory) if img.rpartition('.')[2].lower() in ('jpg', 'png', 'pgm', 'ppm') ])
	# prev_sensor = 0
	# t_matrices = []


	# for i in range(len(images)-1):
	# 	print "Processing ", images[i].split('/')[2], "and ", images[i+1].split('/')[2]
	# 	prev_sensor, K, P, homog_3D, pts_3D, img_pts, img_colours = gen_pt_cloud(i, prev_sensor, images[i], images[i+1])

	# 	if i == 0:
	# 		# first 2 images
	# 		pt_cloud = np.array(pts_3D)
	# 		colours = np.array(img_colours)

	# 	elif i >= 1:
	# 		print "i: ", i

	# 		r_t = np.vstack((np.dot(np.linalg.inv(K), P), np.array([0,0,0,1])))
	# 		print "r_t: ", r_t

			# transform the 3D point set so that it is viewed from camera 1
			# get the matrix that transforms camera --> object coordinate system?
			# tvec is the position of the world origin in camera coords
			# rvec, tvec = cv2.solvePnP(pts_3D, img_pts, K, None)[1:3]
			# print "rvec: ", rvec
			# print "tvec: ", tvec
			# t = np.vstack((np.hstack((cv2.Rodrigues(rvec)[0], tvec)), np.array([0,0,0,1])))
			# print "t :", t
			# t_matrices.append(t)
			# print "# t_matrices: ", range(len(t_matrices))

			# transform the 3D points using the camera pose; homog_3D remains a 4xN array
			# for j in reversed(range(i)):
			# 	print "multiplying with cam_poses[",j,"]"			
			# 	homog_3D = np.array([ np.dot(np.linalg.inv(t_matrices[j]), homog_3D) ])[0]

			# pts_3D = homog_3D[:3].T
			# print "pt_cloud shape: ", pt_cloud.shape
			# print "homog_3D shape: ", pts_3D.shape
			# pt_cloud = np.vstack((pt_cloud, pts_3D))
			# colours = np.vstack((colours, img_colours))

			# print "pt_cloud: ", pt_cloud.shape
			# print "colours: ", colours.shape
		 
	# homog_pt_cloud = np.vstack((pt_cloud.T, np.ones(pt_cloud.shape[0])))

	# draw.draw_matches(src_pts, dst_pts, img1_gray, img2_gray)
	# draw.draw_epilines(src_pts, dst_pts, img1_gray, img2_gray, F, mask)
	# draw.draw_projected_points(homog_pt_cloud, P)
	# np.savetxt('points/homog_3D.txt', [pt for pt in homog_3D])
	# np.savetxt('points/ucd_coffeeshack_1-2.txt', [pt for pt in pt_cloud])
	# pt_cloud = np.loadtxt('points/ucd_building4_1-2.txt')
	# pt_cloud = np.loadtxt('points/alcatraz.txt')
	# draw.display_pyglet(pt_cloud, colours)
	# vtk_cloud.vtk_show_points(pt_cloud)


# main()

homog_3D = np.loadtxt('points/homog_3D.txt')
pts_3D = np.loadtxt('points/alcatraz.txt')
delaunay(homog_3D, pts_3D)