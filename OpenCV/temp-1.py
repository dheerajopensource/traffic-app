import gi

from threading import Thread
from time import sleep

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")

from gi.repository import Gst, GstApp, GLib

_= GstApp

Gst.init()


main_loop = GLib.MainLoop()
main_loop_thread = Thread(target=main_loop.run)
main_loop_thread.start()

# pipeline = Gst.parse_launch("v4l2src ! decodebin ! videoconvert ! autovideosink")
pipeline = Gst.parse_launch("nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), framerate=21/1,format=NV12 ! video/x-raw, width='+str(width)+', height='+str(height)+', format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink name=dk")
appsink = pipeline.get_by_name("dk")
pipeline.set_state(Gst.State.PLAYING)

try:
    while True:
        sample = appsink.try_pull_sample(Gst.SECOND)
        if sample is None:
            continue
    
        print("Got a sample!")
except KeyboardInterrupt:
    pass

pipeline.set_state(Gst.State.NULL)
main_loop.quit()
main_loop_thread.join()