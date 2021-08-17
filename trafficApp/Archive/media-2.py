import os
import sys

from eventlib import Event, make_class_level_events
from weaklib import WeakMethod

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib, Gtk, Gdk

# Needed for window.get_xid(), xvimagesink.set_window_handle(), respectively:
gi.require_version('GstVideo', '1.0')
from gi.repository import GdkX11, GstVideo

Gst.init(None)


if sys.platform == 'win32':
    import ctypes
    
    ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
    ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object]
    
    def get_window_handle(widget):
        if not widget.ensure_native():
            raise Exception('video playback requires a native window')
        
        drawingarea_gpointer = ctypes.pythonapi.PyCapsule_GetPointer(widget.__gpointer__, None)
        gdkdll = ctypes.CDLL('libgdk-3-0.dll')
        handle = gdkdll.gdk_win32_window_get_handle(drawingarea_gpointer)
        
        return handle
else:
    def get_window_handle(widget):
        return widget.get_window().get_xid()


def connect_blocking(widget, event, callback):
    def cb(*args, **kwargs):
        widget.handler_block(cb_id)
        
        retval = callback(*args, **kwargs)
        
        widget.handler_unblock(cb_id)
    
    cb_id = widget.connect(event, cb)


def make_icon_button(icon, cls=Gtk.Button, size=30):
    icon = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
    
    button = cls.new()
    button.add(icon)
    button.set_size_request(size, size)
    button.set_hexpand(False)
    button.set_halign(Gtk.Align.START)
    button.set_vexpand(False)
    button.set_valign(Gtk.Align.END)
    return button


def mainloop_do(callback, *args, **kwargs):
    def cb(_None):
        callback(*args, **kwargs)
        return False
    
    Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT, cb, None)


class Medium:
    make_class_level_events(locals(), 'meta_data_updated')
    
    def __init__(self, uri):
        self.uri = uri
        
        self._title = None
        self._artist = None
        self._album = None
        self._duration = None
        self._num_video_streams = None
        self._num_audio_streams = None
        self._num_subtitle_streams = None
        self._video_width = None
        self._video_height = None
        
    @classmethod
    def from_path(cls, path):
        uri = 'file://' + path
        return cls.from_uri(uri)
    
    @classmethod
    def from_uri(cls, uri):
        return cls(uri)
    
    def __getattr__(self, attr):
        try:
            return vars(self)['_'+attr]
        except KeyError:
            raise AttributeError(attr)
    
    def __setattr__(self, attr, value):
        attrs = vars(self)
        
        if attr.startswith('_') or '_'+attr not in attrs:
            attrs[attr] = value
        else:
            attrs['_'+attr] = value
            self.meta_data_updated.emit()
    
    @property
    def has_video(self):
        if self.num_video_streams is None:
            return None
            
        return self.num_video_streams > 0
    
    @property
    def has_audio(self):
        if self.num_audio_streams is None:
            return None
            
        return self.num_audio_streams > 0
    
    @property
    def has_subtitles(self):
        if self.num_subtitle_streams is None:
            return None
        
        return self.num_subtitle_streams > 0
    
    def __str__(self):
        if self.title:
            return self.title
        
        return os.path.basename(self.path)
    
    def __repr__(self):
        cls_name = type(self).__qualname__
        return '{}({!r})>'.format(cls_name, self.uri)


class VideoCanvas(Gtk.DrawingArea):
    make_class_level_events(locals(), 'window_handle_changed', argnames=('handle',))
    
    def __init__(self):
        super().__init__()
        
        self.set_hexpand(True)
        self.set_vexpand(True)
        
        self._window_handle = None
        
        self.connect('realize', self._on_realize)
        self.connect('unrealize', self._on_unrealize)
    
    @staticmethod
    def _on_realize(self):
        self.window_handle = get_window_handle(self)
        
    @staticmethod
    def _on_unrealize(self):
        self.window_handle = None
    
    @property
    def window_handle(self):
        return self._window_handle
    
    @window_handle.setter
    def window_handle(self, handle):
        self._window_handle = handle
        
        self.window_handle_changed.emit(handle)


class VideoPlayer:
    make_class_level_events(locals(), 'state_changed', argnames=('state',))
    make_class_level_events(locals(), 'volume_changed', argnames=('volume',))
    make_class_level_events(locals(), 'repeat_changed', argnames=('repeat',))
    make_class_level_events(locals(), 'playback_finished')
    
    def __init__(self, canvas, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._canvas = canvas
        
        self._playbin = Gst.ElementFactory.make('playbin', 'playbin')
        
        callback = WeakMethod(self._on_meta_data_found)
        for event in ('video-tags-changed', 'audio-tags-changed'):
            self._playbin.connect(event, callback)
        
        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', self._on_finish)
        bus.connect('message::error', self._on_error)
        bus.enable_sync_message_emission()
        bus.connect('sync-message::element', self._on_sync_message)
        bus.connect('message', self._on_message)
        
        self.medium_changed = Event(argnames=('medium',))
        self._medium = None
        
        self.volume = 0.5
        self.repeat = True
        
        #  self._canvas.window_handle_changed.connect(self._on_window_handle_changed)
        self.connect('destroy', self._on_destroy)
    
    #  def _on_window_handle_changed(self, handle):
        #  if handle is None:
            #  fakesink = Gst.ElementFactory.make("fakesink", "fakesink")
            #  self._playbin.set_property("video-sink", fakesink)
        #  else:
            #  imagesink.set_window_handle(self.window_handle)
    
    def _on_meta_data_found(self, playbin, stream):
        if self.medium.duration is None:
            self.medium.duration = self._playbin.query_duration(Gst.Format.TIME)[1] / Gst.SECOND
    
    @staticmethod
    def _on_destroy(self):
        self.stop()
    
    def _on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            self.stop()
        elif message.type == Gst.MessageType.ERROR:
            self.stop()
            
            err, debug = message.parse_error()
            print('Error: %s' % err, debug)

    def _on_sync_message(self, bus, message):
        if message.get_structure().get_name() == 'prepare-window-handle':
            imagesink = message.src
            imagesink.set_property('force-aspect-ratio', True)
            imagesink.set_window_handle(self._canvas.window_handle)
    
    def _on_error(self, bus, message):
        self.stop()
        
        err, debug = message.parse_error()
        print(err, debug)
    
    def _on_finish(self, bus, message):
        if self.repeat:
            self.playback_finished.emit()
            self._playbin.seek(
                1.0,
                Gst.Format.TIME,
                Gst.SeekFlags.SEGMENT,
                Gst.SeekType.SET, 0,
                Gst.SeekType.NONE, 0
            )
        else:
            self.stop()
            self.playback_finished.emit()
    
    def _set_state(self, state):
        self._playbin.set_state(state)
        
        self.state_changed.emit(state)
    
    @property
    def state(self):
        return self._playbin.get_state(0).state
    
    @property
    def medium(self):
        return self._medium
    
    @medium.setter
    def medium(self, medium):
        self._medium = medium
        
        self._playbin.set_property('uri', medium.uri)
        
        self.medium_changed.emit(medium)
    
    def play_file(self, path):
        medium = Medium.from_path(path)
        self.play(medium)
    
    def play_uri(self, uri):
        medium = Medium.from_uri(uri)
        self.play(medium)
    
    def play(self, medium):
        self.medium = medium
        self.start()
    
    def start(self):
        self._set_state(Gst.State.PLAYING)
    
    def stop(self):
        self._set_state(Gst.State.NULL)
    
    def pause(self):
        self._set_state(Gst.State.PAUSED)
    
    def toggle_play_pause(self):
        if self.state == Gst.State.PLAYING:
            self.pause()
        else:
            self.start()
    
    @property
    def current_time(self):
        return self._playbin.query_position(Gst.Format.TIME)[1] / Gst.SECOND
    
    def seek_to(self, value):
        flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT
        self._playbin.seek_simple(Gst.Format.TIME, flags, value * Gst.SECOND)
    
    def seek_forward(self, value):
        value = min(self.medium.duration, self.current_time + value)
        self.seek_to(value)
        
    def seek_backward(self, value):
        value = max(0, self.current_time - value)
        self.seek_to(value)
    
    @property
    def volume(self):
        return self._playbin.get_property('volume')
    
    @volume.setter
    def volume(self, volume):
        self._playbin.set_property('volume', volume)
        
        self.volume_changed.emit(volume)
    
    @property
    def repeat(self):
        return self._repeat
    
    @repeat.setter
    def repeat(self, repeat):
        self._repeat = repeat
        
        self.repeat_changed.emit(repeat)
    
    @property
    def subtitle_uri(self):
        return self._playbin.get_property('suburi')
        
    @subtitle_uri.setter
    def subtitle_uri(self, uri):
        self._playbin.set_property('suburi', uri)
    
    @property
    def subtitle_font(self):
        return self._playbin.get_property('subtitle-font-desc')
        
    @subtitle_font.setter
    def subtitle_font(self, font):
        self._playbin.set_property('subtitle-font-desc', font)


class VideoPlayerWidget(VideoPlayer, Gtk.Bin):
    def __init__(self):
        canvas = VideoCanvas()
        super().__init__(canvas)
        
        self.add(canvas)


class VideoPlayerWithControls(VideoPlayer, Gtk.Grid):
    def __init__(self):
        canvas = VideoCanvas()
        super().__init__(canvas)
        
        self.attach(canvas, 0, 0, 1, 1)
        
        slider_hbox = Gtk.HBox()
        self._seek_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._seek_slider.set_hexpand(True)
        self._seek_slider.set_halign(Gtk.Align.FILL)
        self._seek_slider.set_draw_value(False)
        self._on_seek_cb_id = self._seek_slider.connect('value-changed', WeakMethod(self._on_seek))
        slider_hbox.pack_start(self._seek_slider, True, True, 0)
        
        self._video_progress_label = Gtk.Label()
        slider_hbox.pack_start(self._video_progress_label, False, False, 0)
        
        buttons_box = Gtk.HBox()
        buttons_box.set_spacing(5)
        
        #~ self.prev_medium_button = make_icon_button('medium-skip-backward')
        #~ self.prev_medium_button.connect('clicked', lambda button:self.play_previous())
        #~ buttons_box.pack_start(self.prev_medium_button, False, False, 0)
        
        self._play_pause_button = make_icon_button('media-playback-start')
        self._play_pause_button.connect('clicked', WeakMethod(self._on_play_pause_button_clicked))
        self.state_changed.connect(WeakMethod(self._on_state_changed), argnames=('state',))
        buttons_box.pack_start(self._play_pause_button, False, False, 0)
        
        #~ self.next_medium_button = make_icon_button('medium-skip-forward')
        #~ self.next_medium_button.connect('clicked', lambda button:self.play_next())
        #~ buttons_box.pack_start(self.next_medium_button, False, False, 0)
        
        #~ self.shuffle_button= make_icon_button('medium-playlist-shuffle', Gtk.ToggleButton)
        #~ self.shuffle_button.set_active(self.playlist.shuffle)
        #~ self.shuffle_button.connect('toggled', self.__shuffle_toggled)
        #~ self.shuffle_button.set_margin_start(30)
        #~ buttons_box.pack_start(self.shuffle_button, False, False, 0)
        
        self._repeat_button = make_icon_button('media-playlist-repeat', Gtk.ToggleButton)
        self._repeat_button.set_active(self.repeat)
        connect_blocking(self._repeat_button, 'toggled', WeakMethod(self._on_repeat_toggled))
        self.repeat_changed.connect(WeakMethod(self._on_repeat_changed), argnames=('repeat',))
        buttons_box.pack_start(self._repeat_button, False, False, 0)
        
        self._volume_button = Gtk.VolumeButton()
        self._volume_button.get_adjustment().set_upper(1.0)
        self._volume_button.get_adjustment().set_step_increment(self._volume_button.get_adjustment().get_upper()/10)
        self._volume_button.get_adjustment().set_page_increment(self._volume_button.get_adjustment().get_upper()/10)
        self._volume_button.connect('value-changed', WeakMethod(self._on_volume_slider_changed))
        
        controls = Gtk.VBox()
        controls.set_hexpand(True)
        controls.set_halign(Gtk.Align.FILL)
        controls.set_vexpand(False)
        controls.set_valign(Gtk.Align.END)
        controls.set_border_width(5)
        self.attach(controls, 0, 1, 1, 1)
        
        controls.pack_start(slider_hbox, True, True, 0)
        buttons_box.pack_end(self._volume_button, False, False, 0)
        controls.pack_start(buttons_box, False, False, 0)
        
        self.connect('key-press-event', self._on_key_pressed)
        
        GLib.timeout_add(1000/30, WeakMethod(self._update_video_position))
    
    def _on_play_pause_button_clicked(self, button):
        self.toggle_play_pause()
    
    def _on_state_changed(self, state):
        if state == Gst.State.PLAYING:
            icon = 'media-playback-pause'
        else:
            icon = 'media-playback-start'
        
        img_widget = self._play_pause_button.get_children()[0]
        mainloop_do(img_widget.set_from_icon_name, icon, Gtk.IconSize.LARGE_TOOLBAR)
    
    def _on_seek(self, scale):
        position = scale.get_value()
        position = self.medium.duration * position / scale.get_adjustment().get_upper()
        self.seek_to(position)
    
    def _on_volume_slider_changed(self, volume_button, value):
        self.volume = value
    
    def _update_video_position(self):
        if self.medium is None or self.medium.duration is None or self.medium.duration <= 0:
            return True
        
        def duration(time):
            result = ''
            time = int(time)
            for mod in (60, 60):
                result = '%02d:%s'%(time%mod, result)
                time = int(time/mod)
                if time == 0:
                    break
            
            result = result[:-1]
            if time > 0 or ':' not in result:
                result = '%02d:%s'%(time%mod, result)
            
            return result
            
        def durations():
            current = duration(current_time)
            total = duration(self.medium.duration)
            current = '00:'*(total.count(':')-current.count(':'))+current
            
            if current.startswith('00'):
                current = current[1:]
            if total.startswith('00'):
                total = total[1:]
            
            return '%s / %s'%(current, total)
        
        self._seek_slider.disconnect(self._on_seek_cb_id)
        
        current_time = self.current_time
        self._seek_slider.set_value(current_time/self.medium.duration*100)
        self._video_progress_label.set_text(durations())
        
        self._on_seek_cb_id = self._seek_slider.connect('value-changed', WeakMethod(self._on_seek))
        
        return True
    
    @staticmethod
    def _on_key_pressed(self, event):
        key = event.keyval
        modifiers = event.state & (Gdk.ModifierType.SHIFT_MASK|Gdk.ModifierType.CONTROL_MASK|Gdk.ModifierType.MOD1_MASK)
        
        if modifiers & Gdk.ModifierType.CONTROL_MASK:
            if not modifiers & ~Gdk.ModifierType.CONTROL_MASK:
                # Control + ...
                if event.keyval == 65363: # rightarrow
                    self.play_next()
                elif event.keyval == 65361: # leftarrow
                    self.play_previous()
                else:
                    return
                return True
        
        if modifiers:
            return
        
        if event.keyval in (65480, 102): # F11 f
            self.toggle_fullscreen()
        elif event.keyval == 65363: # rightarrow
            self.seek_forward()
        elif event.keyval == 65361: # leftarrow
            self.seek_backward()
        elif event.keyval == 32: # spacebar
            self.toggle_play_pause()
        elif event.keyval == 65307: # escape
            self.unfullscreen()
        elif event.keyval == 65362: # uparrow
            self.volume_up()
        elif event.keyval == 65364: # downarrow
            self.volume_down()
        else:
            return
        return True
    
    def _on_repeat_toggled(self, button):
        self.repeat = button.get_active()
    
    def _on_repeat_changed(self, repeat):
        self._repeat_button.set_active(repeat)
    
    def show(self):
        self.show_all()
    

win = Gtk.Window()
win.set_default_size(500, 400)
win.connect('destroy', Gtk.main_quit)

player = VideoPlayerWithControls()
win.add(player)

win.show_all()
player.play_uri('https://thumbs.gfycat.com/FatalFlamboyantGrackle-mobile.mp4')
Gtk.main()