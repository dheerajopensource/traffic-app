import numpy as np
import cv2 as cv
cap = cv.VideoCapture('road.mp4')
pathOut= "/home/dheeraj/dheeraj/trafficApp/frameimg/"
count = 0

while cap.isOpened():
    ret, frame = cap.read()
    # if frame is read correctly ret is True
    if not ret:
        print("Can't receive frame (stream end?). Exiting ...")
        break
    colorful = cv.cvtColor(frame, cv.COLOR_RGB2RGBA)
    cv.imshow('AICadium: TrafficApp', colorful)
    cv.imwrite(pathOut + "/frame%d.jpg" % count, frame)
    print("image saved%d" % count)
    count += 1
    if cv.waitKey(1) == ord('q'):
        break
cap.release()
cv.destroyAllWindows()