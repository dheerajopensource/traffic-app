import cv2
print(cv2.__version__)
width=1280
height=720
flip=1
camSet='nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=3264, height=2464, framerate=21/1,format=NV12 ! nvvidconv flip-method='+str(flip)+' ! video/x-raw, width='+str(width)+', height='+str(height)+', format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink'
#camSet ='v4l2src device=/dev/video1 ! video/x-raw,width='+str(width)+',height='+str(height)+',framerate=24/1 ! videoconvert ! appsink'
camSet1='nvarguscamerasrc !  nvvidconv flip-method=2 ! video/x-raw,width=1280,height=840 ! autovideoconvert ! videoconvert ! appsink'
cam=cv2.VideoCapture(camSet)
while True:
    _, frame = cam.read()
    cv2.imshow('AICadium ProCam',frame)
    cv2.moveWindow('AICadium Live ProCam',0,0)
    if cv2.waitKey(1)==ord('q'):
        break

cam.release()
cv2.destroyAllWindows()
