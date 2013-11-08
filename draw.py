import cv2
import numpy as np
from matplotlib import pyplot as plt
from pylab import *
from scipy import linalg

def draw_matches(src_pts, dst_pts, img1, img2):
	'''Places the 2 images side-by-side and draws lines between matching keypoints.'''
	img1_H, img1_W = img1.shape[:2]
	img2_H, img2_W = img2.shape[:2]

	img_matches = np.zeros((max(img1_H, img2_H), img1_W+img2_W), np.uint8)
	img_matches[:, :img1_W] = img1 # place img1 on the left half
	img_matches[:, img1_W:] = img2 # place img2 on the right half

	for i in range(len(src_pts)):
		pt_a = (int(src_pts[i][0][0]), int(src_pts[i][0][1]))
		pt_b = (int(dst_pts[i][0][0]+img1_W), int(dst_pts[i][0][1]))
		cv2.line(img_matches, pt_a, pt_b, (255,255,255))

	plt.imshow(img_matches,), plt.show()

def draw_epilines(src_pts, dst_pts, img1, img2, F, mask):
	# select only inlier points
	img1_pts = src_pts[mask.ravel()==1]
	img2_pts = dst_pts[mask.ravel()==1]

	# find epilines corresponding to points in the 2nd image and draw them on the 1st image
	lines1 = cv2.computeCorrespondEpilines(img2_pts.reshape(-1,1,2), 2, F)
	lines1 = lines1.reshape(-1,3)
	img5, img6 = draw_lines(img1, img2, lines1, img1_pts, img2_pts)

	# find epilines corresponding to points in the 1st image and draw them on the 2nd image
	lines2 = cv2.computeCorrespondEpilines(img1_pts.reshape(-1,1,2), 1, F)
	lines2 = lines2.reshape(-1,3)
	img3, img4 = draw_lines(img2, img1, lines2, img2_pts, img1_pts)

	plt.subplot(121), plt.imshow(img5)
	plt.subplot(122), plt.imshow(img3)
	plt.show()

def draw_lines(img1, img2, lines, img1_pts, img2_pts):
	h, w = img1.shape
	for r, pt1, pt2 in zip(lines, img1_pts, img2_pts):
		color = tuple(np.random.randint(0,255,3).tolist())
		x0, y0 = [ int(x) for x in [ 0, -r[2]/r[1] ] ]
		x1, y1 = [ int(x) for x in [ w, -(r[2]+r[0]*w) / r[1] ] ]
		cv2.line(img1, (x0,y0), (x1,y1), color, 1)
		cv2.circle(img1, tuple(pt1[0]), 5, color, -1)
		cv2.circle(img2, tuple(pt2[0]), 5, color, -1)

	return img1, img2

class Camera(object):
	"""Class for representing pin-hole cameras."""

	def __init__(self, P):
		"""Initialize P = K[R|t] camera model."""
		self.P = P
		self.K = None # calibration matrix
		self.R = None # rotation
		self.t = None # translation
		self.c = None # camera center

	def project(self, X):
		"""Project points in X (4*n array) and normalize coordinates."""

		x = dot(self.P, X)
		for i in range(3):
			x[i] /= x[2]
		return x

	def rotation_matrix(a):
		"""Creates a 3D rotation matrix for rotation around the axis of the vector a."""
		R = eye(4)
		R[:3,:3] = linalg.expm([[0,-a[2],a[1]], [a[2],0,-a[0]], [-a[1],a[0],0]])
		return R

	def factor(self):
		"""Factorize the camera matrix into K, R, t where P = K[R|t]."""

		# factor first 3*3 part
		K, R = linalg.rq(self.P[:,:3])

		# make diagonal of K positive
		T = diag(sign(diag(K)))
		if linalg.det(T) < 0:
			T[1,1] *= -1

		self.K = dot(K,T)
		self.R = dot(T,R) # T is its own inverse
		self.t = dot(linalg.inv(self.K), self.P[:,3])

		return self.K, self.R, self.t

	def center(self):
		"""Compute and return the camera center."""

		if self.c is not None:
			return self.c
		else:
			# compute c by factoring
			self.factor()
			self.c = -dot(self.R.T, self.t)
			return self.c

def draw_projected_points(homog_3D, P):
	# setup camera
	camera = Camera(P)
	proj_pts = camera.project(homog_3D)

	# plot projection
	plt.figure()
	plt.plot(proj_pts[0], proj_pts[1], 'k.')
	plt.show()

import pyglet
from pyglet.gl import *

def display_pyglet(pts_3D, colours_for_pts):
	'''Draw point cloud using Pyglet's wrapper for OpenGL.'''
	num_pts = pts_3D.shape[0]

	points = tuple(pts_3D.flatten())
	colours = tuple(colours_for_pts.flatten())
	print colours[:3]
	points_list = pyglet.graphics.vertex_list(num_pts, ('v3i', points), ('c3B', colours) )

	window = pyglet.window.Window()

	@window.event
	def on_draw():
		points_list.draw(GL_POINTS)

	pyglet.app.run()